from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, EmailStr, Field, model_validator


AccountRole = Literal["guest", "private", "municipal"]
RegisterRole = Literal["guest", "private"]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    phone: str | None = None
    role: RegisterRole = "guest"
    organisation_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "organisation_name",
            "organization_name",
            "orgName",
            "organisationName",
            "organizationName",
        ),
    )

    @model_validator(mode="after")
    def require_organisation_for_private_operator(self):
        if self.role == "private" and not (self.organisation_name or "").strip():
            raise ValueError("Organisation name is required for private operators")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AccountOrganisationResponse(BaseModel):
    id: int
    name: str
    organisation_type: str
    membership_role: str


class AccountResponse(BaseModel):
    id: int
    email: str
    name: str
    phone: str | None = None
    role: AccountRole | str
    organisations: list[AccountOrganisationResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


ParkingSpaceStatus = Literal["available", "occupied", "reserved", "out_of_service"]
ParkingSpaceType = Literal["normal", "electric", "handicap"]
ParkingLotState = Literal["enabled", "disabled"]


class GeoCoordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ImageFrame(BaseModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class BoundingBox(BaseModel):
    x: float = Field(ge=0, validation_alias=AliasChoices("x", "x_min"))
    y: float = Field(ge=0, validation_alias=AliasChoices("y", "y_min"))
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    frame: ImageFrame | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_bounds(cls, value):
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if "x" not in normalized and "x_min" in normalized:
            normalized["x"] = normalized["x_min"]
        if "y" not in normalized and "y_min" in normalized:
            normalized["y"] = normalized["y_min"]
        if "width" not in normalized and {"x_min", "x_max"}.issubset(normalized):
            normalized["width"] = float(normalized["x_max"]) - float(normalized["x_min"])
        if "height" not in normalized and {"y_min", "y_max"}.issubset(normalized):
            normalized["height"] = float(normalized["y_max"]) - float(normalized["y_min"])
        return normalized


ImageCoordinate = Annotated[float, Field(ge=0)]
ImagePoint = tuple[ImageCoordinate, ImageCoordinate]


class ParkingSpacePolygon(BaseModel):
    points: list[ImagePoint] = Field(min_length=3)
    frame: ImageFrame | None = None


class ParkingSpaceCreate(BaseModel):
    parking_lot_id: int | None = None
    camera_id: int | None = None
    code: str
    zone: str
    level: int = 0
    status: ParkingSpaceStatus = "available"
    space_type: ParkingSpaceType = "normal"
    is_active: bool = True
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    polygon: ParkingSpacePolygon | None = None
    bounding_box: BoundingBox | None = None

    @model_validator(mode="after")
    def require_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        return self


class ParkingSpaceResponse(BaseModel):
    id: int
    parking_lot_id: int | None
    camera_id: int | None
    code: str
    zone: str
    level: int
    status: str
    space_type: str
    is_active: bool
    latitude: float | None
    longitude: float | None
    polygon: ParkingSpacePolygon | None
    bounding_box: BoundingBox | None

    model_config = {"from_attributes": True}


class SpacesPageResponse(BaseModel):
    account: AccountResponse | None
    spaces: list[ParkingSpaceResponse]


CameraType = Literal["panoramic", "number_plate"]


class ParkingLotCameraCreate(BaseModel):
    name: str
    camera_type: CameraType
    stream_url: str
    is_active: bool = True
    is_primary: bool = False


class ParkingLotCameraResponse(BaseModel):
    id: int
    parking_lot_id: int
    name: str
    camera_type: str
    stream_url: str
    is_active: bool
    is_primary: bool

    model_config = {"from_attributes": True}


class ParkingLotCreate(BaseModel):
    name: str
    address: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    state: ParkingLotState = "enabled"
    owner_name: str | None = None
    hourly_rate: float = Field(default=0, ge=0)
    is_free: bool = False
    open_hours: str = "24/7"
    payment_link: str | None = Field(default=None, max_length=500)
    cameras: list[ParkingLotCameraCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lot_details(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        if self.is_free:
            self.hourly_rate = 0
        return self


class ParkingLotUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    state: ParkingLotState | None = None
    owner_name: str | None = None
    hourly_rate: float | None = Field(default=None, ge=0)
    is_free: bool | None = None
    open_hours: str | None = None
    payment_link: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        return self


class ParkingLotResponse(BaseModel):
    id: int
    name: str
    address: str
    total_spots: int
    occupied_spots: int
    space_type_counts: dict[str, int] = Field(default_factory=dict)
    latitude: float | None
    longitude: float | None
    state: str
    owner_name: str | None
    hourly_rate: float
    is_free: bool
    open_hours: str
    payment_link: str | None
    cameras: list[ParkingLotCameraResponse]

    model_config = {"from_attributes": True}


class ParkingLotsPageResponse(BaseModel):
    account: AccountResponse | None
    lots: list[ParkingLotResponse]


class CameraDetectionItem(BaseModel):
    space_id: int | None = None
    space_code: str | None = None
    occupied: bool | None = None
    status: ParkingSpaceStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    polygon: ParkingSpacePolygon | None = None
    bounding_box: BoundingBox | None = None
    detected_at: datetime | None = None

    @model_validator(mode="after")
    def require_detection_target(self):
        if self.space_id is None and not self.space_code and self.bounding_box is None and self.polygon is None:
            raise ValueError("Detection must include space_id, space_code, bounding_box, or polygon")
        if self.status is None and self.occupied is None:
            raise ValueError("Detection must include occupied or status")
        return self


class CameraDetectionBatch(BaseModel):
    source: str | None = None
    generated_at: datetime | None = None
    min_iou: float = Field(default=0.1, ge=0, le=1)
    detections: list[CameraDetectionItem] = Field(default_factory=list)


class CameraOccupancyDetectionRequest(BaseModel):
    image_path: str | None = None
    model_path: str = "yolo26x.pt"
    source: str | None = None
    confidence: float = Field(default=0.15, ge=0, le=1)
    image_size: int = Field(default=1280, ge=320, le=4096)
    occupied_threshold: float = Field(default=0.1, ge=0, le=1)
    vehicle_classes: list[int] | None = Field(default_factory=lambda: [2, 3])
    debug: bool = False
    save_frame_path: str | None = None
    save_output_path: str | None = None
    save_debug_json_path: str | None = None


class SpaceDetectionPayload(BaseModel):
    id: int
    code: str
    status: str
    occupied: bool
    is_active: bool
    space_type: str
    coordinates: GeoCoordinate | None
    polygon: ParkingSpacePolygon | None
    bounding_box: BoundingBox | None
    detection: dict[str, Any] | None


class DetectionUpdateResponse(BaseModel):
    event: Literal["parking_detection_update"] = "parking_detection_update"
    parking_lot_id: int
    camera_id: int
    generated_at: datetime
    source: str | None
    spaces: list[SpaceDetectionPayload]
    unmatched_detections: list[dict[str, Any]]
    debug: dict[str, Any] | None = None


class CameraOccupancyResponse(BaseModel):
    event: Literal["camera_occupancy_snapshot"] = "camera_occupancy_snapshot"
    generated_at: datetime
    parking_lot_id: int
    parking_lot_name: str
    camera_id: int
    camera_name: str
    camera_type: str
    lot_total_spots: int
    lot_occupied_spots: int
    lot_available_spots: int
    lot_space_type_counts: dict[str, int] = Field(default_factory=dict)
    camera_total_spots: int
    camera_occupied_spots: int
    camera_available_spots: int
    spaces: list[SpaceDetectionPayload]


class ParkingSpaceDetectionResponse(BaseModel):
    id: int
    parking_lot_id: int
    camera_id: int
    parking_space_id: int | None
    space_code: str | None
    previous_status: str | None
    status: str
    occupied: bool
    confidence: float | None
    match_iou: float | None
    polygon: ParkingSpacePolygon | None
    bounding_box: BoundingBox | None
    raw_detection: dict[str, Any] | None
    source: str | None
    detected_at: datetime
    received_at: datetime

    model_config = {"from_attributes": True}


class DetectionHistoryResponse(BaseModel):
    detections: list[ParkingSpaceDetectionResponse]


class LicensePlateDetectionHistoryItem(BaseModel):
    id: int
    account_id: int
    source_file: str | None
    image_width: int | None
    image_height: int | None
    model: str | None
    detection_confidence: float | None
    total_detections: int
    parsed_plates: int
    plate: str | None
    compact: str | None
    county_code: str | None
    county_name: str | None
    country_code: str | None
    country_name: str | None
    plate_type: str | None
    raw_ocr: str | None
    confidence: float | None
    bounding_box: BoundingBox | None
    raw_detection: dict[str, Any] | None
    detected_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class LicensePlateDetectionHistoryResponse(BaseModel):
    detections: list[LicensePlateDetectionHistoryItem]
    page: int
    limit: int
    total: int
    total_pages: int
