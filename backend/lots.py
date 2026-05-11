from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import account_response, get_current_account, get_optional_account
from database import get_db
from models import Account, ParkingLot, ParkingLotCamera
from schemas import (
    ParkingLotCameraCreate,
    ParkingLotCameraResponse,
    ParkingLotCreate,
    ParkingLotResponse,
    ParkingLotsPageResponse,
)

router = APIRouter(prefix="/api", tags=["parking lots"])

VALID_CAMERA_TYPES = {"panoramic", "number_plate", "thermal"}


def require_admin(account: Account) -> None:
    if account.role.name != "administrator":
        raise HTTPException(status_code=403, detail="Administrator access required")


def normalize_camera_payload(body: ParkingLotCameraCreate) -> ParkingLotCameraCreate:
    return ParkingLotCameraCreate(
        name=body.name.strip(),
        camera_type=body.camera_type,
        stream_url=body.stream_url.strip(),
    )


def validate_camera_payload(camera: ParkingLotCameraCreate) -> None:
    if not camera.name:
        raise HTTPException(status_code=422, detail="Camera name is required")
    if not camera.stream_url:
        raise HTTPException(status_code=422, detail="Camera stream URL is required")
    if camera.camera_type not in VALID_CAMERA_TYPES:
        raise HTTPException(status_code=422, detail="Invalid camera type")


def lot_response(lot: ParkingLot) -> ParkingLotResponse:
    return ParkingLotResponse.model_validate(lot)


@router.get("/lots", response_model=ParkingLotsPageResponse)
async def list_lots(
    response: Response,
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ParkingLot)
        .options(selectinload(ParkingLot.cameras))
        .order_by(ParkingLot.name)
    )
    lots = result.scalars().all()

    return ParkingLotsPageResponse(
        account=account_response(account) if account else None,
        lots=[lot_response(lot) for lot in lots],
    )


@router.post("/lots", response_model=ParkingLotResponse, status_code=status.HTTP_201_CREATED)
async def create_lot(
    body: ParkingLotCreate,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    name = body.name.strip()
    address = body.address.strip()
    cameras = [normalize_camera_payload(camera) for camera in body.cameras]

    if not name:
        raise HTTPException(status_code=422, detail="Parking lot name is required")
    if not address:
        raise HTTPException(status_code=422, detail="Parking lot address is required")
    if not any(camera.camera_type == "panoramic" for camera in cameras):
        raise HTTPException(status_code=422, detail="At least one panoramic camera is required")

    for camera in cameras:
        validate_camera_payload(camera)

    existing = await db.execute(select(ParkingLot).where(ParkingLot.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Parking lot name already exists")

    lot = ParkingLot(
        name=name,
        address=address,
        total_spots=body.total_spots,
        created_by_id=account.id,
    )
    lot.cameras = [
        ParkingLotCamera(
            name=camera.name,
            camera_type=camera.camera_type,
            stream_url=camera.stream_url,
            created_by_id=account.id,
        )
        for camera in cameras
    ]

    db.add(lot)
    await db.commit()

    result = await db.execute(
        select(ParkingLot)
        .options(selectinload(ParkingLot.cameras))
        .where(ParkingLot.id == lot.id)
    )
    created_lot = result.scalar_one()
    return lot_response(created_lot)


@router.post(
    "/lots/{lot_id}/cameras",
    response_model=ParkingLotCameraResponse,
    status_code=status.HTTP_201_CREATED,
)
async def allocate_camera(
    lot_id: int,
    body: ParkingLotCameraCreate,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    lot = await db.get(ParkingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Parking lot not found")

    payload = normalize_camera_payload(body)
    validate_camera_payload(payload)

    camera = ParkingLotCamera(
        parking_lot_id=lot.id,
        name=payload.name,
        camera_type=payload.camera_type,
        stream_url=payload.stream_url,
        created_by_id=account.id,
    )
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    return ParkingLotCameraResponse.model_validate(camera)
