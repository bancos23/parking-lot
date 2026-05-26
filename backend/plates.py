import io
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from auth import get_current_account
from database import get_db
from models import Account as AccountModel, LicensePlateDetectionHistory
from schemas import LicensePlateDetectionHistoryResponse, LicensePlateDetectionHistoryItem

router = APIRouter(prefix="/api/plates", tags=["license plates"])

BACKEND_DIR = Path(__file__).resolve().parent
PLATE_MODEL_NAME = "best.pt"
PLATE_MODEL_PATH = BACKEND_DIR / PLATE_MODEL_NAME

try:
    import cv2
    import numpy as np
    from ultralytics import YOLO

    _PLATE_YOLO_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None
    YOLO = None
    _PLATE_YOLO_AVAILABLE = False

try:
    import license as plate_lib

    _PLATE_OCR_AVAILABLE = plate_lib.OCR_AVAILABLE
except Exception:
    plate_lib = None
    _PLATE_OCR_AVAILABLE = False

PLATE_MODEL_CACHE: dict[str, Any] = {}

MAX_IMAGE_SIZE = 25 * 1024 * 1024
DETECTION_CONFIDENCE = 0.25
DETECTION_FALLBACK_CONFIDENCE = 0.10
DETECTION_BASE_IMGSZ = 1280
DETECTION_LARGE_IMGSZ = 1536
DETECTION_TILE_MIN_DIM = 1800
DETECTION_TILE_OVERLAP = 0.18


def warm_up_plate_ocr() -> bool:
    if not _PLATE_OCR_AVAILABLE or plate_lib is None:
        return False
    warm_up = getattr(plate_lib, "warm_up_ocr", None)
    if warm_up is None:
        return False
    return bool(warm_up())


def _get_plate_model():
    if not _PLATE_YOLO_AVAILABLE:
        raise HTTPException(status_code=500, detail="YOLO is not installed")
    if not PLATE_MODEL_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Plate model not found: {PLATE_MODEL_NAME}")

    model_path = str(PLATE_MODEL_PATH)
    if model_path not in PLATE_MODEL_CACHE:
        PLATE_MODEL_CACHE[model_path] = YOLO(model_path)
    return PLATE_MODEL_CACHE[model_path]


def _box_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _add_detection(detections: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    for index, existing in enumerate(detections):
        if _box_iou(existing["xyxy"], candidate["xyxy"]) >= 0.45:
            if candidate["confidence"] > existing["confidence"]:
                detections[index] = candidate
            return
    detections.append(candidate)


def _collect_model_boxes(
    model: Any,
    image: Any,
    *,
    conf: float,
    imgsz: int,
    offset_x: int = 0,
    offset_y: int = 0,
) -> list[dict[str, Any]]:
    height, width = image.shape[:2]
    result = model(image, conf=conf, imgsz=imgsz, verbose=False, max_det=20)[0]
    detections = []

    for box in result.boxes:
        score = float(box.conf[0])
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        x1, x2 = max(0, x1) + offset_x, min(width, x2) + offset_x
        y1, y2 = max(0, y1) + offset_y, min(height, y2) + offset_y
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append({"confidence": score, "xyxy": [x1, y1, x2, y2]})

    return detections


def _iter_large_image_tiles(width: int, height: int):
    cols = 2 if width >= DETECTION_TILE_MIN_DIM else 1
    rows = 2 if height >= DETECTION_TILE_MIN_DIM else 1
    if cols == 1 and rows == 1:
        return

    tile_w = (width + cols - 1) // cols
    tile_h = (height + rows - 1) // rows
    overlap_x = int(tile_w * DETECTION_TILE_OVERLAP)
    overlap_y = int(tile_h * DETECTION_TILE_OVERLAP)

    for row in range(rows):
        for col in range(cols):
            x1 = max(0, col * tile_w - overlap_x)
            y1 = max(0, row * tile_h - overlap_y)
            x2 = min(width, (col + 1) * tile_w + overlap_x)
            y2 = min(height, (row + 1) * tile_h + overlap_y)
            if x2 > x1 and y2 > y1:
                yield x1, y1, x2, y2


def _detect_plate_boxes(
    model: Any,
    frame: Any,
    *,
    confidence: float = DETECTION_CONFIDENCE,
) -> list[dict[str, Any]]:
    height, width = frame.shape[:2]
    max_dim = max(width, height)
    imgsz = DETECTION_LARGE_IMGSZ if max_dim >= DETECTION_TILE_MIN_DIM else DETECTION_BASE_IMGSZ
    detections: list[dict[str, Any]] = []

    for candidate in _collect_model_boxes(model, frame, conf=confidence, imgsz=imgsz):
        _add_detection(detections, candidate)

    if max_dim >= DETECTION_TILE_MIN_DIM:
        for x1, y1, x2, y2 in _iter_large_image_tiles(width, height):
            tile = frame[y1:y2, x1:x2]
            for candidate in _collect_model_boxes(
                model,
                tile,
                conf=confidence,
                imgsz=DETECTION_BASE_IMGSZ,
                offset_x=x1,
                offset_y=y1,
            ):
                _add_detection(detections, candidate)

    return sorted(detections, key=lambda item: item["confidence"], reverse=True)


def _crop_plate_region(
    frame: Any,
    box: list[int],
    *,
    left_ratio: float,
    right_ratio: float,
    y_ratio: float,
    min_x: int,
    min_y: int,
) -> Any:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = box
    box_w = x2 - x1
    box_h = y2 - y1
    px_left = max(min_x, int(box_w * left_ratio))
    px_right = max(min_x, int(box_w * right_ratio))
    py = max(min_y, int(box_h * y_ratio))
    cx1, cy1 = max(0, x1 - px_left), max(0, y1 - py)
    cx2, cy2 = min(width, x2 + px_right), min(height, y2 + py)
    return frame[cy1:cy2, cx1:cx2]


def _has_complete_uk_plate(plate: Any) -> bool:
    return (
        getattr(plate, "country_code", None) == "UK"
        and len(getattr(plate, "compact", "") or "") >= 7
    )


def _plate_result_score(plate: Any) -> int:
    if not plate:
        return 0

    compact_len = len(getattr(plate, "compact", "") or "")
    country_code = getattr(plate, "country_code", None)
    if country_code == "UK":
        if compact_len >= 7:
            return 100 + compact_len
        if compact_len >= 6:
            return 60 + compact_len
        return 20 + compact_len
    if country_code == "RO":
        return 90 + compact_len
    if country_code:
        return 40 + compact_len
    return compact_len


def _plate_entry_box(entry: dict[str, Any]) -> list[int] | None:
    bbox = entry.get("bbox") or {}
    try:
        x1 = int(bbox["x"])
        y1 = int(bbox["y"])
        x2 = x1 + int(bbox["width"])
        y2 = y1 + int(bbox["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return [x1, y1, x2, y2]


def _plate_entry_score(entry: dict[str, Any]) -> tuple[int, float, int]:
    compact = entry.get("compact") or ""
    parsed_bonus = 1 if entry.get("plate") else 0
    confidence = float(entry.get("confidence") or 0.0)
    return parsed_bonus, confidence, len(compact)


def _dedupe_plate_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        entry_box = _plate_entry_box(entry)
        entry_compact = entry.get("compact")
        replacement_index = None

        for index, existing in enumerate(deduped):
            existing_compact = existing.get("compact")
            same_plate = entry_compact and existing_compact and entry_compact == existing_compact
            existing_box = _plate_entry_box(existing)
            same_region = (
                entry_box is not None
                and existing_box is not None
                and _box_iou(entry_box, existing_box) >= 0.35
            )
            if same_plate or same_region:
                replacement_index = index
                break

        if replacement_index is None:
            deduped.append(entry)
            continue

        if _plate_entry_score(entry) > _plate_entry_score(deduped[replacement_index]):
            deduped[replacement_index] = entry

    return deduped


def _read_plate_from_detection(frame: Any, box: list[int]) -> tuple[str, Any]:
    if not _PLATE_OCR_AVAILABLE or plate_lib is None:
        return "", None

    primary_crop_specs = [
        {
            "left_ratio": 0.34,
            "right_ratio": 0.42,
            "y_ratio": 0.32,
            "min_x": 24,
            "min_y": 12,
        },
        {
            "left_ratio": 0.50,
            "right_ratio": 0.62,
            "y_ratio": 0.34,
            "min_x": 30,
            "min_y": 14,
        },
    ]
    fallback_crop_specs = [
        {
            "left_ratio": 0.22,
            "right_ratio": 0.22,
            "y_ratio": 0.28,
            "min_x": 18,
            "min_y": 10,
        },
    ]

    best_raw = ""
    best_plate = None
    best_score = 0

    for spec in primary_crop_specs:
        crop = _crop_plate_region(frame, box, **spec)
        raw_text, plate_parsed = plate_lib.read_plate(crop)
        if _has_complete_uk_plate(plate_parsed):
            return raw_text, plate_parsed

        score = _plate_result_score(plate_parsed)
        best_len = len(getattr(best_plate, "compact", "") or "")
        current_len = len(getattr(plate_parsed, "compact", "") or "")
        if score > best_score or (score == best_score and current_len > best_len):
            best_raw = raw_text
            best_plate = plate_parsed
            best_score = score
        elif not best_raw and raw_text:
            best_raw = raw_text

    if best_plate:
        return best_raw, best_plate

    for spec in fallback_crop_specs:
        crop = _crop_plate_region(frame, box, **spec)
        raw_text, plate_parsed = plate_lib.read_plate(crop)
        if _has_complete_uk_plate(plate_parsed):
            return raw_text, plate_parsed

        score = _plate_result_score(plate_parsed)
        if score > best_score:
            best_raw = raw_text
            best_plate = plate_parsed
            best_score = score
        elif not best_raw and raw_text:
            best_raw = raw_text

    return best_raw, best_plate


def _run_plate_detection(image_bytes: bytes) -> dict[str, Any]:
    if not _PLATE_YOLO_AVAILABLE or cv2 is None or np is None:
        raise HTTPException(status_code=500, detail="OpenCV / ultralytics not installed")

    nparr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=422, detail="Could not decode image")

    model = _get_plate_model()
    H, W = frame.shape[:2]

    detections = _detect_plate_boxes(model, frame)
    detection_confidence = DETECTION_CONFIDENCE
    if not detections:
        detections = _detect_plate_boxes(model, frame, confidence=DETECTION_FALLBACK_CONFIDENCE)
        detection_confidence = DETECTION_FALLBACK_CONFIDENCE

    plates = []
    for detection in detections:
        conf = float(detection["confidence"])
        x1, y1, x2, y2 = detection["xyxy"]

        raw_text = ""
        plate_parsed = None

        if _PLATE_OCR_AVAILABLE and plate_lib is not None:
            raw_text, plate_parsed = _read_plate_from_detection(frame, detection["xyxy"])

        plate_entry: dict[str, Any] = {
            "plate": plate_parsed.full if plate_parsed else None,
            "compact": plate_parsed.compact if plate_parsed else None,
            "county_code": plate_parsed.county_code if plate_parsed else None,
            "county_name": plate_parsed.county_name if plate_parsed else None,
            "country_code": getattr(plate_parsed, "country_code", None) if plate_parsed else None,
            "country_name": getattr(plate_parsed, "country_name", None) if plate_parsed else None,
            "plate_type": getattr(plate_parsed, "plate_type", "standard") if plate_parsed else None,
            "raw_ocr": raw_text or None,
            "confidence": round(conf, 3),
            "bbox": {
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": y2 - y1,
            },
        }
        plates.append(plate_entry)

    plates = _dedupe_plate_entries(plates)

    return {
        "image_width": W,
        "image_height": H,
        "model": PLATE_MODEL_NAME,
        "detection_confidence": detection_confidence,
        "plates": plates,
        "total_detections": len(plates),
        "parsed_plates": sum(1 for p in plates if p["plate"] is not None),
    }


async def _store_plate_detection_history(
    db: AsyncSession,
    account: AccountModel,
    result: dict[str, Any],
    *,
    source_file: str | None,
    detected_at: datetime,
) -> None:
    plate_entries = result.get("plates") or [None]

    for plate_entry in plate_entries:
        raw_detection = plate_entry if plate_entry is not None else {"plates": []}
        db.add(
            LicensePlateDetectionHistory(
                account_id=account.id,
                source_file=source_file,
                image_width=result.get("image_width"),
                image_height=result.get("image_height"),
                model=result.get("model"),
                detection_confidence=result.get("detection_confidence"),
                total_detections=result.get("total_detections") or 0,
                parsed_plates=result.get("parsed_plates") or 0,
                plate=plate_entry.get("plate") if plate_entry else None,
                compact=plate_entry.get("compact") if plate_entry else None,
                county_code=plate_entry.get("county_code") if plate_entry else None,
                county_name=plate_entry.get("county_name") if plate_entry else None,
                country_code=plate_entry.get("country_code") if plate_entry else None,
                country_name=plate_entry.get("country_name") if plate_entry else None,
                plate_type=plate_entry.get("plate_type") if plate_entry else None,
                raw_ocr=plate_entry.get("raw_ocr") if plate_entry else None,
                confidence=plate_entry.get("confidence") if plate_entry else None,
                bounding_box=plate_entry.get("bbox") if plate_entry else None,
                raw_detection=raw_detection,
                detected_at=detected_at,
            )
        )

    await db.commit()


@router.post("/detect")
async def detect_plates(
    file: UploadFile = File(...),
    account: AccountModel = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="File must be an image")

    image_bytes = await file.read()
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=422, detail="Image too large (max 25 MB)")

    detected_at = datetime.now(timezone.utc)
    try:
        result = await run_in_threadpool(_run_plate_detection, image_bytes)
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[plates] detection failed: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"Plate detection failed: {exc}") from exc

    result["detected_at"] = detected_at.isoformat()
    result["source_file"] = file.filename

    try:
        await _store_plate_detection_history(
            db,
            account,
            result,
            source_file=file.filename,
            detected_at=detected_at,
        )
    except Exception as exc:
        await db.rollback()
        print(f"[plates] history save failed: {exc}", flush=True)

    return result


@router.get("/history", response_model=LicensePlateDetectionHistoryResponse)
async def plate_detection_history(
    plate: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    account: AccountModel = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    query = select(LicensePlateDetectionHistory).where(
        LicensePlateDetectionHistory.account_id == account.id
    )

    if plate:
        compact = re.sub(r"[^A-Z0-9]", "", plate.upper())
        query = query.where(
            or_(
                LicensePlateDetectionHistory.compact == compact,
                LicensePlateDetectionHistory.plate.ilike(f"%{plate}%"),
                LicensePlateDetectionHistory.raw_ocr.ilike(f"%{plate}%"),
            )
        )
    if country_code:
        query = query.where(LicensePlateDetectionHistory.country_code == country_code.upper())
    if since is not None:
        query = query.where(LicensePlateDetectionHistory.detected_at >= since)
    if until is not None:
        query = query.where(LicensePlateDetectionHistory.detected_at <= until)

    total_result = await db.execute(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    total = int(total_result.scalar_one() or 0)
    total_pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit

    result = await db.execute(
        query.order_by(LicensePlateDetectionHistory.detected_at.desc())
        .offset(offset)
        .limit(limit)
    )
    detections = result.scalars().all()
    return LicensePlateDetectionHistoryResponse(
        detections=[
            LicensePlateDetectionHistoryItem.model_validate(detection)
            for detection in detections
        ],
        page=page,
        limit=limit,
        total=total,
        total_pages=total_pages,
    )
