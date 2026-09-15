from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_account
from config import settings
from database import get_db
from models import Account, ParkingSpace


router = APIRouter(prefix="/api", tags=["statistics"])

DEMO_HOURLY = [18, 14, 12, 11, 16, 28, 45, 63, 72, 76, 71, 68, 74, 81, 86, 83, 77, 70, 64, 58, 51, 45, 36, 26]
HEATMAP_TIMEZONE = ZoneInfo("Europe/Bucharest")
MIN_TRAINING_POINTS = 8
STATS_CACHE: dict[tuple[str, int | None, int, int], dict] = {}
STATS_WARM_LOCK = asyncio.Lock()
STATS_REFRESH_MIN_INTERVAL_SECONDS = settings.stats_refresh_min_interval_seconds
_last_stats_refresh = 0.0


def clamp_percent(value: float) -> int:
    return int(round(min(100, max(0, value))))


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


OCCUPANCY_SERIES_SQL = """
WITH last_states AS (
    SELECT DISTINCT ON (
        date_trunc('hour', detected_at AT TIME ZONE 'UTC'),
        parking_lot_id,
        COALESCE(parking_space_id::text, space_code)
    )
        parking_lot_id,
        date_trunc('hour', detected_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS bucket,
        occupied
    FROM parking_space_detections
    WHERE detected_at >= :since
        AND COALESCE(parking_space_id::text, space_code) IS NOT NULL
{lot_filter}
    ORDER BY
        date_trunc('hour', detected_at AT TIME ZONE 'UTC'),
        parking_lot_id,
        COALESCE(parking_space_id::text, space_code),
        detected_at DESC
)
SELECT
    bucket,
    parking_lot_id,
    count(*) AS spaces,
    count(*) FILTER (WHERE occupied) AS occupied
FROM last_states
GROUP BY bucket, parking_lot_id
ORDER BY bucket
"""


async def occupancy_series(
    db: AsyncSession,
    lot_id: int | None,
    lookback_days: int,
) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    totals = await active_space_totals(db, lot_id)

    lot_filter = "        AND parking_lot_id = :lot_id" if lot_id is not None else ""
    params = {"since": since}
    if lot_id is not None:
        params["lot_id"] = lot_id

    result = await db.execute(text(OCCUPANCY_SERIES_SQL.format(lot_filter=lot_filter)), params)

    bucket_totals: dict[datetime, list[int]] = defaultdict(lambda: [0, 0])
    for row in result.all():
        detected_lot_id = int(row.parking_lot_id)
        lot_total = totals.get(detected_lot_id) or int(row.spaces)
        if lot_total > 0:
            bucket_totals[row.bucket][0] += lot_total
            bucket_totals[row.bucket][1] += int(row.occupied)

    series = [
        {
            "bucket": bucket,
            "occupancy": (occupied_spaces / total_spaces) * 100,
            "occupied_spaces": occupied_spaces,
            "total_spaces": total_spaces,
        }
        for bucket, (total_spaces, occupied_spaces) in sorted(bucket_totals.items())
        if total_spaces > 0
    ]

    return series


def invalidate_stats_cache() -> None:
    STATS_CACHE.clear()


async def forecast_payload(db: AsyncSession, hours: int, lot_id: int | None, lookback_days: int) -> dict:
    key = ("forecast", lot_id, hours, lookback_days)
    if payload := STATS_CACHE.get(key):
        return payload

    series = await occupancy_series(db, lot_id=lot_id, lookback_days=lookback_days)
    trained, model_reason, forecast = await asyncio.to_thread(random_forest_forecast, series, hours)
    actual = actual_points(series, hours)

    if not trained or len(actual) != hours or len(forecast) != hours:
        fallback_actual, fallback_forecast = fallback_points(hours)
        actual = actual if len(actual) == hours else fallback_actual
        forecast = fallback_forecast

    payload = {
        "generated_at": datetime.now(timezone.utc),
        "model": "RandomForestRegressor" if trained else "fallback",
        "model_reason": model_reason,
        "trained": trained,
        "hours": hours,
        "lookback_days": lookback_days,
        "lot_id": lot_id,
        "samples": len(series),
        "actual": actual,
        "forecast": forecast,
    }
    STATS_CACHE[key] = payload
    return payload


async def heatmap_payload(db: AsyncSession, lot_id: int | None, lookback_days: int) -> dict:
    key = ("heatmap", lot_id, 0, lookback_days)
    if payload := STATS_CACHE.get(key):
        return payload

    series = await occupancy_series(db, lot_id=lot_id, lookback_days=lookback_days)
    payload = {
        "generated_at": datetime.now(timezone.utc),
        "lookback_days": lookback_days,
        "lot_id": lot_id,
        "timezone": str(HEATMAP_TIMEZONE),
        "samples": len(series),
        "values": heatmap_values(series),
    }
    STATS_CACHE[key] = payload
    return payload


async def warm_default_stats(session_factory) -> None:
    try:
        async with STATS_WARM_LOCK:
            async with session_factory() as db:
                await forecast_payload(db, hours=24, lot_id=None, lookback_days=90)
                await heatmap_payload(db, lot_id=None, lookback_days=30)
    except Exception:
        pass


def refresh_stats_if_due(session_factory) -> None:
    # Between refreshes the cached payload keeps serving requests, so the
    # hourly aggregates go stale by at most the configured interval.
    global _last_stats_refresh

    if time.monotonic() - _last_stats_refresh < STATS_REFRESH_MIN_INTERVAL_SECONDS:
        return

    _last_stats_refresh = time.monotonic()
    invalidate_stats_cache()
    asyncio.create_task(warm_default_stats(session_factory))


@router.get("/stats/occupancy-forecast")
async def occupancy_forecast(
    hours: int = Query(default=24, ge=6, le=48),
    lot_id: int | None = Query(default=None, ge=1),
    lookback_days: int = Query(default=90, ge=1, le=365),
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    return {**await forecast_payload(db, hours, lot_id, lookback_days), "account_id": account.id if account else None}


@router.get("/stats/occupancy-heatmap")
async def occupancy_heatmap(
    lookback_days: int = Query(default=30, ge=1, le=365),
    lot_id: int | None = Query(default=None, ge=1),
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    return {**await heatmap_payload(db, lot_id, lookback_days), "account_id": account.id if account else None}
