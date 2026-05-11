from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AccountResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


class ParkingSpaceCreate(BaseModel):
    code: str
    zone: str
    level: str = "Ground"
    status: str = "available"


class ParkingSpaceResponse(BaseModel):
    id: int
    code: str
    zone: str
    level: str
    status: str

    model_config = {"from_attributes": True}


class SpacesPageResponse(BaseModel):
    account: AccountResponse | None
    spaces: list[ParkingSpaceResponse]


CameraType = Literal["panoramic", "number_plate", "thermal"]


class ParkingLotCameraCreate(BaseModel):
    name: str
    camera_type: CameraType
    stream_url: str


class ParkingLotCameraResponse(BaseModel):
    id: int
    parking_lot_id: int
    name: str
    camera_type: str
    stream_url: str

    model_config = {"from_attributes": True}


class ParkingLotCreate(BaseModel):
    name: str
    address: str
    total_spots: int = Field(default=0, ge=0)
    cameras: list[ParkingLotCameraCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def require_panoramic_camera(self):
        if not any(camera.camera_type == "panoramic" for camera in self.cameras):
            raise ValueError("At least one panoramic camera is required")
        return self


class ParkingLotResponse(BaseModel):
    id: int
    name: str
    address: str
    total_spots: int
    cameras: list[ParkingLotCameraResponse]

    model_config = {"from_attributes": True}


class ParkingLotsPageResponse(BaseModel):
    account: AccountResponse | None
    lots: list[ParkingLotResponse]
