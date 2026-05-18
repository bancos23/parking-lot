import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from auth import get_current_account
from database import get_db
from models import Account, ParkingLot, ParkingLotCamera, ParkingSpace, ParkingSpaceDetection
from schemas import (
    BoundingBox,
    CameraDetectionBatch,
    CameraOccupancyDetectionRequest,
    CameraOccupancyResponse,
    DetectionHistoryResponse,
    DetectionUpdateResponse,
    ParkingSpaceDetectionResponse,
    ParkingSpacePolygon,
)

router = APIRouter(prefix="/api", tags=["parking detections"])

try:
    import cv2
    import numpy as np
    from ultralytics import YOLO
except ImportError:
    cv2 = None
    np = None
    YOLO = None

YOLO_MODELS: dict[str, Any] = {}
BACKEND_DIR = Path(__file__).resolve().parent
YOLO26X_MODEL_NAME = "yolo26x.pt"
YOLO26X_MODEL_PATH = BACKEND_DIR / YOLO26X_MODEL_NAME
DEBUG_OUTPUT_DIR = BACKEND_DIR / "debug_outputs"
BACKGROUND_DETECTION_INTERVAL_SECONDS = 60
IMAGE_URL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
MJPEG_URL_EXTENSIONS = (".mjpeg", ".mjpg")
URL_FRAME_TIMEOUT_SECONDS = 12
URL_IMAGE_MAX_BYTES = 25 * 1024 * 1024
URL_STREAM_FRAME_MAX_BYTES = 4 * 1024 * 1024


def require_admin(account: Account) -> None:
    if account.role.name not in {"administrator", "municipal", "private"}:
        raise HTTPException(status_code=403, detail="Parking operator access required")


def coordinates_payload(latitude: float | None, longitude: float | None) -> dict[str, float] | None:
    if latitude is None or longitude is None:
        return None
    return {"latitude": latitude, "longitude": longitude}


def bbox_payload(box: BoundingBox | dict[str, Any] | None) -> dict[str, float] | None:
    if box is None:
        return None
    if isinstance(box, BoundingBox):
        return box.model_dump(mode="json")
    parsed = BoundingBox.model_validate(box)
    return parsed.model_dump(mode="json")


def polygon_payload(polygon: ParkingSpacePolygon | dict[str, Any] | None) -> dict[str, Any] | None:
    if polygon is None:
        return None
    if isinstance(polygon, ParkingSpacePolygon):
        return polygon.model_dump(mode="json")
    parsed = ParkingSpacePolygon.model_validate(polygon)
    return parsed.model_dump(mode="json")


def bbox_from_polygon(polygon: ParkingSpacePolygon | dict[str, Any] | None) -> dict[str, float] | None:
    payload = polygon_payload(polygon)
    if not payload:
        return None

    points = payload["points"]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x = min(xs)
    min_y = min(ys)
    width = max(xs) - min_x
    height = max(ys) - min_y
    if width <= 0 or height <= 0:
        return None
    return {"x": min_x, "y": min_y, "width": width, "height": height}


def space_match_box(space: ParkingSpace) -> dict[str, float] | None:
    return bbox_payload(space.bounding_box) or bbox_from_polygon(space.polygon)


def detection_match_box(detection) -> dict[str, float] | None:
    return bbox_payload(detection.bounding_box) or bbox_from_polygon(detection.polygon)


def bbox_iou(first: dict[str, float] | None, second: dict[str, float] | None) -> float:
    if not first or not second:
        return 0

    first_right = first["x"] + first["width"]
    first_bottom = first["y"] + first["height"]
    second_right = second["x"] + second["width"]
    second_bottom = second["y"] + second["height"]

    overlap_width = max(0, min(first_right, second_right) - max(first["x"], second["x"]))
    overlap_height = max(0, min(first_bottom, second_bottom) - max(first["y"], second["y"]))
    intersection = overlap_width * overlap_height
    if intersection == 0:
        return 0

    first_area = first["width"] * first["height"]
    second_area = second["width"] * second["height"]
    return intersection / (first_area + second_area - intersection)


def detection_status(occupied: bool | None, status: str | None) -> str:
    if status:
        return status
    return "occupied" if occupied else "available"


def space_event_payload(space: ParkingSpace, detection: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": space.id,
        "code": space.code,
        "status": space.status,
        "occupied": space.status == "occupied",
        "is_active": space.is_active,
        "space_type": space.space_type,
        "coordinates": coordinates_payload(space.latitude, space.longitude),
        "polygon": polygon_payload(space.polygon),
        "bounding_box": space_match_box(space),
        "detection": detection,
    }


def active_lot_spaces(spaces: list[ParkingSpace]) -> list[ParkingSpace]:
    return [space for space in spaces if space.is_active]


def camera_visible_spaces(camera: ParkingLotCamera, spaces: list[ParkingSpace]) -> list[ParkingSpace]:
    return [
        space
        for space in spaces
        if space.is_active and (space.camera_id is None or space.camera_id == camera.id)
    ]


def require_detector_dependencies() -> None:
    if cv2 is None or np is None or YOLO is None:
        raise HTTPException(
            status_code=500,
            detail="YOLO detection requires opencv-python, numpy, and ultralytics to be installed",
        )


def get_yolo_model():
    require_detector_dependencies()

    model_path = str(YOLO26X_MODEL_PATH)
    if not YOLO26X_MODEL_PATH.exists():
        raise HTTPException(status_code=500, detail=f"YOLO model file not found: {YOLO26X_MODEL_PATH}")

    if model_path not in YOLO_MODELS:
        YOLO_MODELS[model_path] = YOLO(model_path)
    return YOLO_MODELS[model_path]


def is_http_source(source: str) -> bool:
    scheme = urlparse(source).scheme.lower()
    return scheme in {"http", "https"}


def source_path(source: str) -> str:
    return urlparse(source).path.lower()


def looks_like_image_url(source: str) -> bool:
    return source_path(source).endswith(IMAGE_URL_EXTENSIONS)


def looks_like_mjpeg_url(source: str) -> bool:
    return source_path(source).endswith(MJPEG_URL_EXTENSIONS)


def decode_image_bytes(data: bytes, source: str):
    if not data:
        raise HTTPException(status_code=422, detail=f"Camera URL returned an empty frame: {source}")

    image_buffer = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=422, detail=f"Could not decode image frame from: {source}")

    return image


def extract_jpeg_frame(data: bytes) -> bytes | None:
    start = data.find(b"\xff\xd8")
    if start < 0:
        return None

    end = data.find(b"\xff\xd9", start + 2)
    if end < 0:
        return None

    return data[start : end + 2]


def read_limited_response(response, source: str, max_bytes: int) -> bytes:
    data = response.read(max_bytes + 1)

    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=422, detail=f"Camera frame is larger than {max_mb}MB: {source}")

    return data


def read_http_image_frame(source: str):
    request = Request(
        source,
        headers={
            "User-Agent": "ParkingLotDetector/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    try:
        with urlopen(request, timeout=URL_FRAME_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type().lower()
            content_length = response.headers.get("Content-Length")
            is_image_response = content_type.startswith("image/")
            is_mjpeg_response = "multipart" in content_type or "mjpeg" in content_type
            should_read = (
                is_image_response
                or is_mjpeg_response
                or looks_like_image_url(source)
                or looks_like_mjpeg_url(source)
            )

            if not should_read:
                return None

            max_bytes = URL_STREAM_FRAME_MAX_BYTES if is_mjpeg_response else URL_IMAGE_MAX_BYTES
            try:
                response_size = int(content_length) if content_length else None
            except ValueError:
                response_size = None

            if response_size and response_size > max_bytes:
                max_mb = max_bytes // (1024 * 1024)
                raise HTTPException(status_code=422, detail=f"Camera frame is larger than {max_mb}MB: {source}")

            data = read_limited_response(response, source, max_bytes)
    except HTTPException:
        raise
    except HTTPError as error:
        raise HTTPException(status_code=422, detail=f"Could not fetch camera frame ({error.code}): {source}") from error
    except (TimeoutError, URLError) as error:
        raise HTTPException(status_code=422, detail=f"Could not fetch camera frame from: {source}") from error
    except OSError as error:
        raise HTTPException(status_code=422, detail=f"Could not read camera frame from: {source}") from error

    if is_mjpeg_response or looks_like_mjpeg_url(source):
        jpeg_frame = extract_jpeg_frame(data)
        if jpeg_frame is not None:
            return decode_image_bytes(jpeg_frame, source), f"{source}#mjpeg-frame"

    image = decode_image_bytes(data, source)
    return image, source


def is_video_source(source: str) -> bool:
    return "://" in source or source.lower().startswith(("rtsp:", "rtmp:"))


def read_camera_frame(camera_stream_url: str, image_path: str | None):
    require_detector_dependencies()

    source = image_path or camera_stream_url
    if not source:
        raise HTTPException(status_code=422, detail="Camera stream URL or image_path is required")

    if not is_video_source(source) and Path(source).exists():
        image = cv2.imread(source)
        if image is None:
            raise HTTPException(status_code=422, detail=f"Could not read image: {source}")
        return image, source

    if is_http_source(source):
        image_frame = read_http_image_frame(source)
        if image_frame is not None:
            return image_frame

    capture = cv2.VideoCapture(source)
    try:
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        frame = None
        for _ in range(3):
            ok, candidate = capture.read()
            if ok and candidate is not None:
                frame = candidate
    finally:
        capture.release()

    if frame is None:
        raise HTTPException(status_code=422, detail=f"Could not read frame from: {source}")

    return frame, source


def resolve_output_path(output_path: str) -> Path:
    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_debug_image(output_path: str, image, label: str) -> str:
    path = resolve_output_path(output_path)
    saved = cv2.imwrite(str(path), image)

    if not saved:
        raise HTTPException(status_code=500, detail=f"Could not save {label} to {path}")

    print(f"[parking-detection] saved {label}: {path}", flush=True)
    return str(path)


def ensure_debug_output_paths(
    body: CameraOccupancyDetectionRequest,
    camera_id: int,
    generated_at: datetime,
) -> None:
    if not body.debug:
        return

    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    stem = f"camera_{camera_id}_{timestamp}"
    DEBUG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if body.save_frame_path is None:
        body.save_frame_path = str(DEBUG_OUTPUT_DIR / f"{stem}_frame.png")
    if body.save_output_path is None:
        body.save_output_path = str(DEBUG_OUTPUT_DIR / f"{stem}_result.png")
    if body.save_debug_json_path is None:
        body.save_debug_json_path = str(DEBUG_OUTPUT_DIR / f"{stem}.json")


def yolo_boxes(results) -> list[dict[str, Any]]:
    boxes = []
    class_names = getattr(results, "names", {}) or {}

    if results.boxes is None:
        return boxes

    for box in results.boxes:
        xyxy = box.xyxy[0].cpu().numpy()
        cls_id = int(box.cls[0])
        boxes.append(
            {
                "box": xyxy,
                "class_id": cls_id,
                "class_name": class_names.get(cls_id, str(cls_id)) if isinstance(class_names, dict) else str(cls_id),
                "conf": float(box.conf[0]),
            }
        )

    return boxes


def clean_detection_polygon(points):
    polygon = np.array(points, dtype=np.float32)

    if len(polygon) > 1 and np.allclose(polygon[0], polygon[-1]):
        polygon = polygon[:-1]

    return polygon


def polygon_area(polygon) -> float:
    return abs(cv2.contourArea(polygon.astype(np.float32)))


def vehicle_footprint(box, image_shape, shrink_x=0.18, top_y=0.55):
    height, width = image_shape[:2]
    x1, y1, x2, y2 = map(float, box)

    x1 = max(0, min(x1, width - 1))
    x2 = max(0, min(x2, width - 1))
    y1 = max(0, min(y1, height - 1))
    y2 = max(0, min(y2, height - 1))

    box_width = x2 - x1
    box_height = y2 - y1

    foot_x1 = x1 + box_width * shrink_x
    foot_x2 = x2 - box_width * shrink_x
    foot_y1 = y1 + box_height * top_y
    foot_y2 = y2

    if foot_x2 <= foot_x1 or foot_y2 <= foot_y1:
        return None

    return np.array(
        [
            [foot_x1, foot_y1],
            [foot_x2, foot_y1],
            [foot_x2, foot_y2],
            [foot_x1, foot_y2],
        ],
        dtype=np.float32,
    )


def box_anchor_point(box) -> tuple[float, float]:
    x1, y1, x2, y2 = map(float, box)
    return ((x1 + x2) / 2, y2 - (y2 - y1) * 0.05)


def detection_box_payload(box) -> dict[str, float]:
    x1, y1, x2, y2 = map(float, box)
    return {
        "x": x1,
        "y": y1,
        "width": max(0.0, x2 - x1),
        "height": max(0.0, y2 - y1),
    }


def xyxy_payload(box) -> list[float]:
    return [float(value) for value in box]


def polygon_bounds(points) -> dict[str, float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return {
        "x_min": min(xs),
        "y_min": min(ys),
        "x_max": max(xs),
        "y_max": max(ys),
    }


def contour_payload(points) -> list[list[float]]:
    return [[float(point[0]), float(point[1])] for point in points]


def raw_polygon_payload(polygon: ParkingSpacePolygon | dict[str, Any] | None) -> dict[str, Any] | None:
    if polygon is None:
        return None
    if isinstance(polygon, ParkingSpacePolygon):
        return polygon.model_dump(mode="json")
    return polygon


def region_from_space(space: ParkingSpace) -> dict[str, Any] | None:
    payload = raw_polygon_payload(space.polygon)
    if not payload:
        return None

    points = payload.get("points", [])
    if len(points) < 3:
        return None

    frame = payload.get("frame") or {}

    return {
        "space": space,
        "id": space.code,
        "points": np.array(points, dtype=np.float32),
        "frame_width": frame.get("width"),
        "frame_height": frame.get("height"),
    }


def regions_from_spaces(spaces: list[ParkingSpace]) -> list[dict[str, Any]]:
    require_detector_dependencies()

    regions = []
    for space in spaces:
        region = region_from_space(space)
        if region:
            regions.append(region)
    return regions


def scale_points_to_image(points, image_shape, frame_width=None, frame_height=None):
    image_height, image_width = image_shape[:2]
    scaled = np.array(points, dtype=np.float32)

    if frame_width and frame_height and (frame_width != image_width or frame_height != image_height):
        scaled[:, 0] *= image_width / float(frame_width)
        scaled[:, 1] *= image_height / float(frame_height)

    return scaled


def scale_regions_to_image(regions: list[dict[str, Any]], image_shape) -> list[dict[str, Any]]:
    scaled_regions = []
    image_height, image_width = image_shape[:2]

    for region in regions:
        frame_width = region.get("frame_width")
        frame_height = region.get("frame_height")
        scaled_points = scale_points_to_image(
            region["points"],
            image_shape,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        scaled_regions.append(
            {
                **region,
                "points": scaled_points.astype(np.int32),
                "scale": {
                    "x": image_width / float(frame_width) if frame_width else 1.0,
                    "y": image_height / float(frame_height) if frame_height else 1.0,
                    "source_width": frame_width,
                    "source_height": frame_height,
                    "image_width": image_width,
                    "image_height": image_height,
                },
            }
        )

    return scaled_regions


def calculate_camera_parking_status(
    image_shape,
    regions: list[dict[str, Any]],
    boxes: list[dict[str, Any]],
    occupied_threshold: float,
) -> tuple[int, int, list[dict[str, Any]]]:
    prepared_spots = []

    for region in regions:
        polygon = clean_detection_polygon(region["points"])
        area = polygon_area(polygon)

        if area <= 0:
            continue

        prepared_spots.append(
            {
                "space": region["space"],
                "id": region["id"],
                "points": polygon,
                "area": area,
            }
        )

    vehicle_shapes = []

    for index, detected in enumerate(boxes):
        footprint = vehicle_footprint(image_shape=image_shape, box=detected["box"])
        if footprint is not None:
            vehicle_shapes.append(
                {
                    "index": index,
                    "box": detected["box"],
                    "footprint": footprint,
                    "class_id": detected["class_id"],
                    "class_name": detected["class_name"],
                    "conf": detected["conf"],
                }
            )

    occupied = 0
    available = 0
    spot_results = []

    for spot in prepared_spots:
        best_overlap = 0.0
        best_vehicle = None
        anchor_hit = False
        anchor_point = None

        for vehicle in vehicle_shapes:
            overlap_area, _ = cv2.intersectConvexConvex(
                spot["points"].astype(np.float32),
                vehicle["footprint"].astype(np.float32),
            )

            ratio = overlap_area / spot["area"]
            if ratio > best_overlap:
                best_overlap = ratio
                best_vehicle = vehicle

            anchor = box_anchor_point(vehicle["box"])
            if cv2.pointPolygonTest(spot["points"], anchor, False) >= 0:
                anchor_hit = True
                anchor_point = anchor
                best_vehicle = vehicle

        is_occupied = anchor_hit or best_overlap >= occupied_threshold
        status = "occupied" if is_occupied else "available"

        if is_occupied:
            occupied += 1
        else:
            available += 1

        spot_results.append(
            {
                "space": spot["space"],
                "id": spot["id"],
                "status": status,
                "occupied": is_occupied,
                "overlap": best_overlap,
                "anchor_hit": anchor_hit,
                "anchor_point": anchor_point,
                "vehicle": best_vehicle,
                "polygon_bounds": polygon_bounds(spot["points"]),
                "polygon_points": contour_payload(spot["points"]),
            }
        )

    return occupied, available, spot_results


def draw_camera_detection_output(
    image,
    regions: list[dict[str, Any]],
    boxes: list[dict[str, Any]],
    spot_results: list[dict[str, Any]],
    occupied: int,
    available: int,
    model_name: str,
    output_path: str,
) -> None:
    output = image.copy()
    status_by_id = {result["id"]: result for result in spot_results}

    for region in regions:
        polygon = region["points"]
        result = status_by_id.get(region["id"])
        if not result:
            continue

        color = (0, 0, 255) if result["occupied"] else (0, 255, 0)
        cv2.polylines(output, [polygon], True, color, 3)

        moments = cv2.moments(polygon)
        if moments["m00"] != 0:
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
        else:
            cx, cy = map(int, polygon[0])

        cv2.putText(
            output,
            f"{region['id']} {result['overlap']:.2f}",
            (cx - 35, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            color,
            1,
        )

    for detected in boxes:
        x1, y1, x2, y2 = map(int, detected["box"])
        cv2.rectangle(output, (x1, y1), (x2, y2), (255, 255, 255), 1)

        footprint = vehicle_footprint(detected["box"], output.shape)
        if footprint is not None:
            cv2.polylines(output, [footprint.astype(np.int32)], True, (0, 255, 255), 2)

        anchor = box_anchor_point(detected["box"])
        cv2.circle(output, (int(anchor[0]), int(anchor[1])), 4, (255, 0, 255), -1)

        cv2.putText(
            output,
            f"{detected['class_id']} {detected['conf']:.2f}",
            (x1, max(20, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
        )

    cv2.putText(
        output,
        f"Model: {model_name}",
        (40, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        output,
        f"Occupied: {occupied} / {len(regions)}   Available: {available}",
        (40, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
    )

    write_debug_image(output_path, output, "annotated detection image")


def run_yolo_camera_detection(
    camera_stream_url: str,
    regions: list[dict[str, Any]],
    body: CameraOccupancyDetectionRequest,
) -> dict[str, Any]:
    image, image_source = read_camera_frame(camera_stream_url, body.image_path)
    image_regions = scale_regions_to_image(regions, image.shape)
    model = get_yolo_model()

    if body.save_frame_path:
        write_debug_image(body.save_frame_path, image, "captured frame")

    results = model.predict(
        image,
        conf=body.confidence,
        imgsz=body.image_size,
        classes=body.vehicle_classes,
        verbose=False,
    )[0]

    boxes = yolo_boxes(results)
    occupied, available, spot_results = calculate_camera_parking_status(
        image.shape,
        image_regions,
        boxes,
        body.occupied_threshold,
    )

    if body.save_output_path:
        draw_camera_detection_output(
            image=image,
            regions=image_regions,
            boxes=boxes,
            spot_results=spot_results,
            occupied=occupied,
            available=available,
            model_name=YOLO26X_MODEL_NAME,
            output_path=body.save_output_path,
        )

    return {
        "image_source": image_source,
        "model": YOLO26X_MODEL_NAME,
        "model_path": str(YOLO26X_MODEL_PATH),
        "image_width": image.shape[1],
        "image_height": image.shape[0],
        "regions_configured": len(regions),
        "regions_used": len(image_regions),
        "occupied": occupied,
        "available": available,
        "detections": len(boxes),
        "boxes": boxes,
        "spot_results": spot_results,
        "image_regions": image_regions,
    }


def vehicle_debug_payload(box: dict[str, Any], image_shape: tuple[int, int, int]) -> dict[str, Any]:
    footprint = vehicle_footprint(box["box"], image_shape)

    return {
        "class_id": box["class_id"],
        "class_name": box.get("class_name"),
        "confidence": box["conf"],
        "xyxy": xyxy_payload(box["box"]),
        "bounding_box": detection_box_payload(box["box"]),
        "anchor_point": list(box_anchor_point(box["box"])),
        "footprint": contour_payload(footprint) if footprint is not None else None,
    }


def matched_vehicle_debug_payload(vehicle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not vehicle:
        return None

    return {
        "index": vehicle["index"],
        "class_id": vehicle["class_id"],
        "class_name": vehicle.get("class_name"),
        "confidence": vehicle["conf"],
        "xyxy": xyxy_payload(vehicle["box"]),
        "bounding_box": detection_box_payload(vehicle["box"]),
        "anchor_point": list(box_anchor_point(vehicle["box"])),
        "footprint": contour_payload(vehicle["footprint"]),
    }


def build_detection_debug_payload(
    camera: ParkingLotCamera,
    regions: list[dict[str, Any]],
    detection_result: dict[str, Any],
    body: CameraOccupancyDetectionRequest,
) -> dict[str, Any]:
    spaces_debug = []

    for result in detection_result["spot_results"]:
        spaces_debug.append(
            {
                "space_id": result["space"].id,
                "code": result["space"].code,
                "status": result["status"],
                "occupied": result["occupied"],
                "overlap": result["overlap"],
                "anchor_hit": result["anchor_hit"],
                "anchor_point": list(result["anchor_point"]) if result["anchor_point"] else None,
                "polygon_bounds": result["polygon_bounds"],
                "polygon_points": result["polygon_points"],
                "matched_vehicle": matched_vehicle_debug_payload(result["vehicle"]),
            }
        )

    image_shape = (
        detection_result["image_height"],
        detection_result["image_width"],
        3,
    )

    return {
        "camera_id": camera.id,
        "camera_stream_url": camera.stream_url,
        "image_source": detection_result["image_source"],
        "image_width": detection_result["image_width"],
        "image_height": detection_result["image_height"],
        "model_path": detection_result["model_path"],
        "model": detection_result["model"],
        "confidence": body.confidence,
        "image_size": body.image_size,
        "vehicle_classes": body.vehicle_classes,
        "occupied_threshold": body.occupied_threshold,
        "regions_configured": detection_result["regions_configured"],
        "regions_used": detection_result["regions_used"],
        "vehicle_detections": detection_result["detections"],
        "occupied": detection_result["occupied"],
        "available": detection_result["available"],
        "saved_frame_path": body.save_frame_path,
        "saved_output_path": body.save_output_path,
        "saved_debug_json_path": body.save_debug_json_path,
        "vehicles": [vehicle_debug_payload(box, image_shape) for box in detection_result["boxes"]],
        "spaces": spaces_debug,
        "region_scales": [
            {
                "code": region["id"],
                "scale": region.get("scale"),
                "bounds": polygon_bounds(region["points"]),
            }
            for region in regions
        ],
    }


def space_type_counts(spaces: list[ParkingSpace]) -> dict[str, int]:
    counts = {"normal": 0, "electric": 0, "handicap": 0}
    for space in spaces:
        if space.space_type in counts:
            counts[space.space_type] += 1
    return counts


def occupied_spaces(spaces: list[ParkingSpace]) -> int:
    return sum(1 for space in spaces if space.status == "occupied")


def available_spaces(spaces: list[ParkingSpace]) -> int:
    return sum(1 for space in spaces if space.status == "available")


def match_detection_to_space(
    detection,
    spaces_by_id: dict[int, ParkingSpace],
    spaces_by_code: dict[str, ParkingSpace],
    bbox_candidates: list[ParkingSpace],
    min_iou: float,
) -> tuple[ParkingSpace | None, float | None]:
    if detection.space_id is not None:
        return spaces_by_id.get(detection.space_id), None

    if detection.space_code:
        return spaces_by_code.get(detection.space_code.strip().upper()), None

    incoming_box = detection_match_box(detection)
    if not incoming_box:
        return None, None

    best_space = None
    best_iou = 0.0
    for space in bbox_candidates:
        score = bbox_iou(incoming_box, space_match_box(space))
        if score > best_iou:
            best_iou = score
            best_space = space

    if best_iou < min_iou:
        return None, best_iou
    return best_space, best_iou


def detection_request_payload(camera: ParkingLotCamera, body: CameraOccupancyDetectionRequest) -> str:
    return (
        "[parking-detection] detect request "
        f"camera_id={camera.id} "
        f"debug={body.debug} "
        f"model_path={YOLO26X_MODEL_PATH} "
        f"image_path={body.image_path} "
        f"stream_url={camera.stream_url} "
        f"save_frame_path={body.save_frame_path} "
        f"save_output_path={body.save_output_path} "
        f"save_debug_json_path={body.save_debug_json_path}"
    )


async def run_camera_occupancy_detection(
    camera_id: int,
    body: CameraOccupancyDetectionRequest,
    db: AsyncSession,
) -> DetectionUpdateResponse:
    require_detector_dependencies()

    camera = await db.get(ParkingLotCamera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Parking lot camera not found")
    if not camera.is_active:
        raise HTTPException(status_code=409, detail="Parking lot camera is inactive")

    result = await db.execute(
        select(ParkingSpace)
        .where(
            ParkingSpace.parking_lot_id == camera.parking_lot_id,
            ParkingSpace.is_active.is_(True),
            ParkingSpace.polygon.is_not(None),
            or_(ParkingSpace.camera_id.is_(None), ParkingSpace.camera_id == camera.id),
        )
        .order_by(ParkingSpace.zone, ParkingSpace.code)
    )
    spaces = result.scalars().all()
    regions = regions_from_spaces(spaces)

    if not regions:
        raise HTTPException(
            status_code=409,
            detail="No active parking spaces with polygon data are configured for this camera",
        )

    generated_at = datetime.now(timezone.utc)
    ensure_debug_output_paths(body, camera.id, generated_at)

    print(detection_request_payload(camera, body), flush=True)

    detection_result = await run_in_threadpool(run_yolo_camera_detection, camera.stream_url, regions, body)
    detection_source = body.source or f"yolo:{detection_result['model']}"
    debug_payload = None

    if body.debug or body.save_debug_json_path:
        debug_payload = build_detection_debug_payload(
            camera=camera,
            regions=detection_result["image_regions"],
            detection_result=detection_result,
            body=body,
        )

        if body.save_debug_json_path:
            debug_json_path = resolve_output_path(body.save_debug_json_path)
            with debug_json_path.open("w", encoding="utf-8") as debug_file:
                json.dump(debug_payload, debug_file, indent=2)
            print(f"[parking-detection] saved debug json: {debug_json_path}", flush=True)

    print(
        "[parking-detection] result "
        f"camera_id={camera.id} "
        f"vehicles={detection_result['detections']} "
        f"occupied={detection_result['occupied']} "
        f"available={detection_result['available']} "
        f"image={detection_result['image_width']}x{detection_result['image_height']} "
        f"regions={detection_result['regions_used']}",
        flush=True,
    )

    detections_by_space_id: dict[int, dict[str, Any]] = {}

    for spot_result in detection_result["spot_results"]:
        space = spot_result["space"]
        previous_status = space.status
        new_status = spot_result["status"]
        vehicle = spot_result["vehicle"]
        vehicle_box = detection_box_payload(vehicle["box"]) if vehicle else None
        confidence = vehicle["conf"] if vehicle else None
        raw_detection = {
            "model": detection_result["model"],
            "image_source": detection_result["image_source"],
            "image_width": detection_result["image_width"],
            "image_height": detection_result["image_height"],
            "regions_configured": detection_result["regions_configured"],
            "regions_used": detection_result["regions_used"],
            "total_vehicle_detections": detection_result["detections"],
            "occupied_threshold": body.occupied_threshold,
            "overlap": spot_result["overlap"],
            "anchor_hit": spot_result["anchor_hit"],
            "vehicle": {
                "class_id": vehicle["class_id"],
                "class_name": vehicle.get("class_name"),
                "confidence": vehicle["conf"],
                "bounding_box": vehicle_box,
            }
            if vehicle
            else None,
        }

        space.status = new_status
        db.add(
            ParkingSpaceDetection(
                parking_lot_id=camera.parking_lot_id,
                camera_id=camera.id,
                parking_space_id=space.id,
                space_code=space.code,
                previous_status=previous_status,
                status=new_status,
                occupied=spot_result["occupied"],
                confidence=confidence,
                match_iou=spot_result["overlap"],
                bounding_box=vehicle_box,
                polygon=space.polygon,
                raw_detection=raw_detection,
                source=detection_source,
                detected_at=generated_at,
            )
        )

        detections_by_space_id[space.id] = {
            "matched": True,
            "status": new_status,
            "occupied": spot_result["occupied"],
            "confidence": confidence,
            "image_width": detection_result["image_width"],
            "image_height": detection_result["image_height"],
            "total_vehicle_detections": detection_result["detections"],
            "bounding_box": vehicle_box,
            "polygon": polygon_payload(space.polygon),
            "match_iou": spot_result["overlap"],
            "anchor_hit": spot_result["anchor_hit"],
            "detected_at": generated_at,
        }

    await db.commit()

    return DetectionUpdateResponse(
        parking_lot_id=camera.parking_lot_id,
        camera_id=camera.id,
        generated_at=generated_at,
        source=detection_source,
        spaces=[
            space_event_payload(space, detections_by_space_id.get(space.id))
            for space in spaces
        ],
        unmatched_detections=[],
        debug=debug_payload,
    )


async def active_occupancy_camera_ids(session_factory) -> list[int]:
    async with session_factory() as db:
        result = await db.execute(
            select(ParkingLotCamera.id)
            .join(ParkingLot, ParkingLot.id == ParkingLotCamera.parking_lot_id)
            .where(
                ParkingLotCamera.is_active.is_(True),
                ParkingLotCamera.camera_type == "panoramic",
                ParkingLotCamera.stream_url != "",
                ParkingLot.state == "enabled",
            )
            .order_by(ParkingLotCamera.id)
        )
        return list(result.scalars().all())


async def detect_active_camera_occupancy_once(session_factory) -> None:
    camera_ids = await active_occupancy_camera_ids(session_factory)
    if not camera_ids:
        return

    print(f"[parking-detection] background scan cameras={len(camera_ids)}", flush=True)

    for camera_id in camera_ids:
        async with session_factory() as db:
            try:
                await run_camera_occupancy_detection(
                    camera_id,
                    CameraOccupancyDetectionRequest(source="background-live-feed"),
                    db,
                )
            except HTTPException as error:
                await db.rollback()
                print(
                    "[parking-detection] background camera skipped "
                    f"camera_id={camera_id} "
                    f"status={error.status_code} "
                    f"detail={error.detail}",
                    flush=True,
                )
            except Exception as error:
                await db.rollback()
                print(
                    "[parking-detection] background camera failed "
                    f"camera_id={camera_id} "
                    f"error={error}",
                    flush=True,
                )


async def background_occupancy_detection_loop(
    session_factory,
    interval_seconds: int = BACKGROUND_DETECTION_INTERVAL_SECONDS,
) -> None:
    print(f"[parking-detection] background scheduler started interval={interval_seconds}s", flush=True)

    try:
        while True:
            started_at = datetime.now(timezone.utc)
            try:
                await detect_active_camera_occupancy_once(session_factory)
            except Exception as error:
                print(f"[parking-detection] background scan failed error={error}", flush=True)

            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            await asyncio.sleep(max(1, interval_seconds - elapsed))
    except asyncio.CancelledError:
        print("[parking-detection] background scheduler stopped", flush=True)
        raise


def start_occupancy_detection_scheduler(
    session_factory,
    interval_seconds: int = BACKGROUND_DETECTION_INTERVAL_SECONDS,
) -> asyncio.Task | None:
    if cv2 is None or np is None or YOLO is None:
        print("[parking-detection] background scheduler not started: detector dependencies are missing", flush=True)
        return None

    return asyncio.create_task(
        background_occupancy_detection_loop(session_factory, interval_seconds),
        name="parking-occupancy-detection",
    )


async def stop_occupancy_detection_scheduler(task: asyncio.Task | None) -> None:
    if task is None:
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@router.get("/cameras/{camera_id}/occupancy", response_model=CameraOccupancyResponse)
async def camera_occupancy_snapshot(
    camera_id: int,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    result = await db.execute(
        select(ParkingLotCamera)
        .options(
            selectinload(ParkingLotCamera.parking_lot).selectinload(ParkingLot.spaces),
        )
        .where(ParkingLotCamera.id == camera_id)
    )
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Parking lot camera not found")
    if not camera.is_active:
        raise HTTPException(status_code=409, detail="Parking lot camera is inactive")

    lot = camera.parking_lot
    lot_spaces = active_lot_spaces(lot.spaces)
    visible_spaces = camera_visible_spaces(camera, lot.spaces)
    lot_occupied = occupied_spaces(lot_spaces)
    lot_available = available_spaces(lot_spaces)
    camera_occupied = occupied_spaces(visible_spaces)
    camera_available = available_spaces(visible_spaces)

    return CameraOccupancyResponse(
        generated_at=datetime.now(timezone.utc),
        parking_lot_id=lot.id,
        parking_lot_name=lot.name,
        camera_id=camera.id,
        camera_name=camera.name,
        camera_type=camera.camera_type,
        lot_total_spots=len(lot_spaces),
        lot_occupied_spots=lot_occupied,
        lot_available_spots=lot_available,
        lot_space_type_counts=space_type_counts(lot_spaces),
        camera_total_spots=len(visible_spaces),
        camera_occupied_spots=camera_occupied,
        camera_available_spots=camera_available,
        spaces=[
            space_event_payload(space, None)
            for space in sorted(visible_spaces, key=lambda space: (space.zone, space.code))
        ],
    )


@router.get("/lots/{lot_id}/detection-config")
async def lot_detection_config(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ParkingLot)
        .options(selectinload(ParkingLot.cameras), selectinload(ParkingLot.spaces))
        .where(ParkingLot.id == lot_id)
    )
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail="Parking lot not found")

    spaces = sorted(lot.spaces, key=lambda space: (space.zone, space.code))
    cameras = sorted(
        [camera for camera in lot.cameras if camera.is_active],
        key=lambda camera: (not camera.is_primary, camera.name),
    )

    return {
        "event": "parking_detection_config",
        "generated_at": datetime.now(timezone.utc),
        "parking_lot": {
            "id": lot.id,
            "name": lot.name,
            "address": lot.address,
            "total_spots": sum(1 for space in spaces if space.is_active),
        },
        "cameras": [
            {
                "id": camera.id,
                "name": camera.name,
                "camera_type": camera.camera_type,
                "stream_url": camera.stream_url,
                "is_active": camera.is_active,
                "is_primary": camera.is_primary,
                "space_codes": [
                    space.code
                    for space in spaces
                    if space.camera_id is None or space.camera_id == camera.id
                ],
            }
            for camera in cameras
        ],
        "spaces": [
            {
                "id": space.id,
                "code": space.code,
                "zone": space.zone,
                "level": space.level,
                "status": space.status,
                "is_active": space.is_active,
                "space_type": space.space_type,
                "camera_id": space.camera_id,
                "coordinates": coordinates_payload(space.latitude, space.longitude),
                "polygon": polygon_payload(space.polygon),
                "bounding_box": space_match_box(space),
            }
            for space in spaces
        ],
    }


@router.get("/lots/{lot_id}/detections/history", response_model=DetectionHistoryResponse)
async def lot_detection_history(
    lot_id: int,
    camera_id: int | None = Query(default=None),
    space_id: int | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    lot = await db.get(ParkingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Parking lot not found")

    query = select(ParkingSpaceDetection).where(ParkingSpaceDetection.parking_lot_id == lot_id)
    if camera_id is not None:
        query = query.where(ParkingSpaceDetection.camera_id == camera_id)
    if space_id is not None:
        query = query.where(ParkingSpaceDetection.parking_space_id == space_id)
    if since is not None:
        query = query.where(ParkingSpaceDetection.detected_at >= since)
    if until is not None:
        query = query.where(ParkingSpaceDetection.detected_at <= until)

    result = await db.execute(query.order_by(ParkingSpaceDetection.detected_at.desc()).limit(limit))
    detections = result.scalars().all()
    return DetectionHistoryResponse(
        detections=[
            ParkingSpaceDetectionResponse.model_validate(detection)
            for detection in detections
        ]
    )


@router.post("/cameras/{camera_id}/detect-occupancy", response_model=DetectionUpdateResponse)
async def detect_camera_occupancy(
    camera_id: int,
    body: CameraOccupancyDetectionRequest,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)
    return await run_camera_occupancy_detection(camera_id, body, db)


@router.post("/cameras/{camera_id}/detections", response_model=DetectionUpdateResponse)
async def receive_camera_detections(
    camera_id: int,
    body: CameraDetectionBatch,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    camera = await db.get(ParkingLotCamera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Parking lot camera not found")
    if not camera.is_active:
        raise HTTPException(status_code=409, detail="Parking lot camera is inactive")

    result = await db.execute(
        select(ParkingSpace)
        .where(ParkingSpace.parking_lot_id == camera.parking_lot_id)
        .order_by(ParkingSpace.zone, ParkingSpace.code)
    )
    spaces = result.scalars().all()
    spaces_by_id = {space.id: space for space in spaces}
    spaces_by_code = {space.code.upper(): space for space in spaces}
    bbox_candidates = [
        space
        for space in spaces
        if (space.bounding_box or space.polygon) and (space.camera_id is None or space.camera_id == camera.id)
    ]

    generated_at = body.generated_at or datetime.now(timezone.utc)
    detections_by_space_id: dict[int, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []

    for detection in body.detections:
        detected_at = detection.detected_at or generated_at
        incoming_box = detection_match_box(detection)
        incoming_polygon = polygon_payload(detection.polygon)
        raw_detection = detection.model_dump(mode="json", exclude_none=True)
        space, match_iou = match_detection_to_space(
            detection,
            spaces_by_id,
            spaces_by_code,
            bbox_candidates,
            body.min_iou,
        )
        new_status = detection_status(detection.occupied, detection.status)

        if not space:
            db.add(
                ParkingSpaceDetection(
                    parking_lot_id=camera.parking_lot_id,
                    camera_id=camera.id,
                    parking_space_id=None,
                    space_code=detection.space_code.strip().upper() if detection.space_code else None,
                    previous_status=None,
                    status=new_status,
                    occupied=new_status == "occupied",
                    confidence=detection.confidence,
                    match_iou=match_iou,
                    bounding_box=incoming_box,
                    polygon=incoming_polygon,
                    raw_detection=raw_detection,
                    source=body.source,
                    detected_at=detected_at,
                )
            )
            unmatched.append(
                {
                    "space_id": detection.space_id,
                    "space_code": detection.space_code,
                    "status": new_status,
                    "occupied": new_status == "occupied",
                    "confidence": detection.confidence,
                    "bounding_box": incoming_box,
                    "polygon": incoming_polygon,
                    "match_iou": match_iou,
                    "reason": "No configured parking space matched this detection",
                }
            )
            continue

        previous_status = space.status
        space.status = new_status
        db.add(
            ParkingSpaceDetection(
                parking_lot_id=camera.parking_lot_id,
                camera_id=camera.id,
                parking_space_id=space.id,
                space_code=space.code,
                previous_status=previous_status,
                status=new_status,
                occupied=new_status == "occupied",
                confidence=detection.confidence,
                match_iou=match_iou,
                bounding_box=incoming_box,
                polygon=incoming_polygon,
                raw_detection=raw_detection,
                source=body.source,
                detected_at=detected_at,
            )
        )
        detections_by_space_id[space.id] = {
            "matched": True,
            "status": new_status,
            "occupied": new_status == "occupied",
            "confidence": detection.confidence,
            "bounding_box": incoming_box,
            "polygon": incoming_polygon,
            "match_iou": match_iou,
            "detected_at": detected_at,
        }

    await db.commit()

    return DetectionUpdateResponse(
        parking_lot_id=camera.parking_lot_id,
        camera_id=camera.id,
        generated_at=generated_at,
        source=body.source,
        spaces=[
            space_event_payload(space, detections_by_space_id.get(space.id))
            for space in spaces
        ],
        unmatched_detections=unmatched,
    )
