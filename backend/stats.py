from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_account
from database import get_db
from models import Account, ParkingSpace, ParkingSpaceDetection


router = APIRouter(prefix="/api", tags=["statistics"])

DEMO_HOURLY = [18, 14, 12, 11, 16, 28, 45, 63, 72, 76, 71, 68, 74, 81, 86, 83, 77, 70, 64, 58, 51, 45, 36, 26]
HEATMAP_TIMEZONE = ZoneInfo("Europe/Bucharest")
MIN_TRAINING_POINTS = 8


def clamp_percent(value: float) -> int:
    return int(round(min(100, max(0, value))))


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hour_bucket(value: datetime) -> datetime:
    value = normalize_datetime(value)
    return value.replace(minute=0, second=0, microsecond=0)


def hour_label(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%H:00")


def feature_row(value: datetime, previous: float, rolling_average: float) -> list[float]:
    weekday = value.weekday()
    hour = value.hour
    return [
        float(hour),
        float(weekday),
        1.0 if weekday >= 5 else 0.0,
        math.sin((2 * math.pi * hour) / 24),
        math.cos((2 * math.pi * hour) / 24),
        float(previous),
        float(rolling_average),
    ]


def fallback_points(hours: int) -> tuple[list[dict], list[dict]]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    actual_values = (DEMO_HOURLY * 3)[-hours:]
    forecast_values = [
        clamp_percent(value + math.sin(index * 0.6) * 4 + 2)
        for index, value in enumerate(actual_values)
    ]
    actual = [
        {
            "label": hour_label(now - timedelta(hours=hours - index)),
            "occupancy": clamp_percent(value),
        }
        for index, value in enumerate(actual_values)
    ]
    forecast = [
        {
            "label": hour_label(now + timedelta(hours=index + 1)),
            "occupancy": value,
        }
        for index, value in enumerate(forecast_values)
    ]
    return actual, forecast


def actual_points(series: list[dict], hours: int) -> list[dict]:
    points = series[-hours:]
    return [
        {
            "label": hour_label(point["bucket"]),
            "occupancy": clamp_percent(point["occupancy"]),
        }
        for point in points
    ]


def heatmap_values(series: list[dict]) -> list[list[int | None]]:
    grouped: dict[tuple[int, int], list[float]] = defaultdict(list)

    for point in series:
        local_bucket = normalize_datetime(point["bucket"]).astimezone(HEATMAP_TIMEZONE)
        grouped[(local_bucket.weekday(), local_bucket.hour)].append(float(point["occupancy"]))

    return [
        [
            clamp_percent(sum(values) / len(values)) if (values := grouped.get((weekday, hour))) else None
            for hour in range(24)
        ]
        for weekday in range(7)
    ]


def random_forest_forecast(series: list[dict], hours: int) -> tuple[bool, str, list[dict]]:
    if len(series) < MIN_TRAINING_POINTS:
        return False, "insufficient_history", []

    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        return False, "scikit_learn_missing", []

    values = [float(point["occupancy"]) for point in series]
    features: list[list[float]] = []
    targets: list[float] = []

    for index in range(1, len(series)):
        previous_values = values[max(0, index - 3):index]
        features.append(
            feature_row(
                series[index]["bucket"],
                previous=values[index - 1],
                rolling_average=sum(previous_values) / len(previous_values),
            )
        )
        targets.append(values[index])

    if len(features) < MIN_TRAINING_POINTS - 1:
        return False, "insufficient_training_rows", []

    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42,
        min_samples_leaf=1,
    )
    model.fit(features, targets)

    generated: list[dict] = []
    rolling_values = list(values)
    next_bucket = series[-1]["bucket"] + timedelta(hours=1)

    for _ in range(hours):
        previous_values = rolling_values[-3:]
        prediction = float(
            model.predict(
                [
                    feature_row(
                        next_bucket,
                        previous=rolling_values[-1],
                        rolling_average=sum(previous_values) / len(previous_values),
                    )
                ]
            )[0]
        )
        occupancy = clamp_percent(prediction)
        generated.append(
            {
                "label": hour_label(next_bucket),
                "occupancy": occupancy,
            }
        )
        rolling_values.append(float(occupancy))
        next_bucket += timedelta(hours=1)

    return True, "random_forest", generated


async def active_space_totals(db: AsyncSession, lot_id: int | None) -> dict[int, int]:
    stmt = (
        select(ParkingSpace.parking_lot_id, func.count(ParkingSpace.id))
        .where(ParkingSpace.is_active.is_(True), ParkingSpace.parking_lot_id.is_not(None))
        .group_by(ParkingSpace.parking_lot_id)
    )
    if lot_id is not None:
        stmt = stmt.where(ParkingSpace.parking_lot_id == lot_id)

    result = await db.execute(stmt)
    return {int(row[0]): int(row[1]) for row in result.all() if row[0] is not None}


async def occupancy_series(
    db: AsyncSession,
    lot_id: int | None,
    lookback_days: int,
) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    totals = await active_space_totals(db, lot_id)

    stmt = (
        select(
            ParkingSpaceDetection.parking_lot_id,
            ParkingSpaceDetection.parking_space_id,
            ParkingSpaceDetection.space_code,
            ParkingSpaceDetection.occupied,
            ParkingSpaceDetection.detected_at,
        )
        .where(ParkingSpaceDetection.detected_at >= since)
        .order_by(ParkingSpaceDetection.detected_at.asc())
    )
    if lot_id is not None:
        stmt = stmt.where(ParkingSpaceDetection.parking_lot_id == lot_id)

    result = await db.execute(stmt)
    states_by_bucket: dict[tuple[datetime, int], dict[str, bool]] = defaultdict(dict)

    for row in result.all():
        detected_lot_id = int(row.parking_lot_id)
        space_key = row.parking_space_id or row.space_code
        if not space_key:
            continue

        states_by_bucket[(hour_bucket(row.detected_at), detected_lot_id)][str(space_key)] = bool(row.occupied)

    buckets = sorted({bucket for bucket, _ in states_by_bucket})
    series: list[dict] = []

    for bucket in buckets:
        total_spaces = 0
        occupied_spaces = 0

        for (state_bucket, state_lot_id), states in states_by_bucket.items():
            if state_bucket != bucket:
                continue
            lot_total = totals.get(state_lot_id) or len(states)
            if lot_total <= 0:
                continue
            total_spaces += lot_total
            occupied_spaces += sum(1 for occupied in states.values() if occupied)

        if total_spaces <= 0:
            continue

        series.append(
            {
                "bucket": bucket,
                "occupancy": (occupied_spaces / total_spaces) * 100,
                "occupied_spaces": occupied_spaces,
                "total_spaces": total_spaces,
            }
        )

    return series


@router.get("/stats/occupancy-forecast")
async def occupancy_forecast(
    hours: int = Query(default=24, ge=6, le=48),
    lot_id: int | None = Query(default=None, ge=1),
    lookback_days: int = Query(default=90, ge=1, le=365),
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    series = await occupancy_series(db, lot_id=lot_id, lookback_days=lookback_days)
    trained, model_reason, forecast = random_forest_forecast(series, hours)
    actual = actual_points(series, hours)

    if not trained or len(actual) != hours or len(forecast) != hours:
        fallback_actual, fallback_forecast = fallback_points(hours)
        actual = actual if len(actual) == hours else fallback_actual
        forecast = fallback_forecast

    return {
        "generated_at": datetime.now(timezone.utc),
        "model": "RandomForestRegressor" if trained else "fallback",
        "model_reason": model_reason,
        "trained": trained,
        "hours": hours,
        "lookback_days": lookback_days,
        "lot_id": lot_id,
        "samples": len(series),
        "account_id": account.id if account else None,
        "actual": actual,
        "forecast": forecast,
    }


@router.get("/stats/occupancy-heatmap")
async def occupancy_heatmap(
    lookback_days: int = Query(default=30, ge=1, le=365),
    lot_id: int | None = Query(default=None, ge=1),
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    series = await occupancy_series(db, lot_id=lot_id, lookback_days=lookback_days)

    return {
        "generated_at": datetime.now(timezone.utc),
        "lookback_days": lookback_days,
        "lot_id": lot_id,
        "timezone": str(HEATMAP_TIMEZONE),
        "samples": len(series),
        "account_id": account.id if account else None,
        "values": heatmap_values(series),
    }
