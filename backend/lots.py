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
    ParkingLotUpdate,
    ParkingLotsPageResponse,
)

router = APIRouter(prefix="/api", tags=["parking lots"])

VALID_CAMERA_TYPES = {"panoramic", "number_plate"}
VALID_LOT_STATES = {"enabled", "disabled"}
SPACE_TYPE_ALIASES = {"charging_station": "electric"}


def require_admin(account: Account) -> None:
    if account.role.name not in {"administrator", "municipal", "private"}:
        raise HTTPException(status_code=403, detail="Parking operator access required")


def normalize_camera_payload(body: ParkingLotCameraCreate) -> ParkingLotCameraCreate:
    return ParkingLotCameraCreate(
        name=body.name.strip(),
        camera_type=body.camera_type,
        stream_url=body.stream_url.strip(),
        is_active=body.is_active,
        is_primary=body.is_primary,
    )


def validate_camera_payload(camera: ParkingLotCameraCreate) -> None:
    if not camera.name:
        raise HTTPException(status_code=422, detail="Camera name is required")
    if not camera.stream_url:
        raise HTTPException(status_code=422, detail="Camera stream URL is required")
    if camera.camera_type not in VALID_CAMERA_TYPES:
        raise HTTPException(status_code=422, detail="Invalid camera type")
    if camera.is_primary and camera.camera_type != "panoramic":
        raise HTTPException(status_code=422, detail="Primary live feed camera must be panoramic")
    if camera.is_primary and not camera.is_active:
        raise HTTPException(status_code=422, detail="Primary live feed camera must be active")


def primary_camera_index(cameras: list[ParkingLotCameraCreate]) -> int:
    explicit_primary = [index for index, camera in enumerate(cameras) if camera.is_primary]
    if len(explicit_primary) > 1:
        raise HTTPException(status_code=422, detail="Only one primary live feed camera is allowed per parking lot")
    if explicit_primary:
        return explicit_primary[0]

    for index, camera in enumerate(cameras):
        if camera.camera_type == "panoramic" and camera.is_active:
            return index

    raise HTTPException(status_code=422, detail="Parking lot requires at least one active panoramic camera")


def normalize_optional_text(value: str | None) -> str | None:
    normalized = " ".join(value.strip().split()) if value else ""
    return normalized or None


def default_owner_name(account: Account) -> str | None:
    if account.role.name in {"administrator", "municipal"}:
        return "Primăria Baia Mare"
    return normalize_optional_text(account.name) or account.email


def validate_lot_state(state: str) -> None:
    if state not in VALID_LOT_STATES:
        raise HTTPException(status_code=422, detail="Invalid parking lot state")


def normalized_space_type(space_type: str) -> str:
    return SPACE_TYPE_ALIASES.get(space_type, space_type)


def lot_total_spots(lot: ParkingLot) -> int:
    return sum(1 for space in lot.spaces if space.is_active)


def lot_space_type_counts(lot: ParkingLot) -> dict[str, int]:
    counts = {"normal": 0, "electric": 0, "handicap": 0}
    for space in lot.spaces:
        if not space.is_active:
            continue
        space_type = normalized_space_type(space.space_type)
        if space_type in counts:
            counts[space_type] += 1
    return counts


def lot_response(lot: ParkingLot) -> ParkingLotResponse:
    occupied_spots = sum(1 for space in lot.spaces if space.is_active and space.status == "occupied")
    return ParkingLotResponse(
        id=lot.id,
        name=lot.name,
        address=lot.address,
        total_spots=lot_total_spots(lot),
        occupied_spots=occupied_spots,
        space_type_counts=lot_space_type_counts(lot),
        latitude=lot.latitude,
        longitude=lot.longitude,
        state=lot.state,
        owner_name=lot.owner_name,
        hourly_rate=lot.hourly_rate,
        is_free=lot.is_free,
        open_hours=lot.open_hours,
        payment_link=lot.payment_link,
        cameras=[ParkingLotCameraResponse.model_validate(camera) for camera in lot.cameras],
    )


@router.get("/lots", response_model=ParkingLotsPageResponse)
async def list_lots(
    response: Response,
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ParkingLot)
        .options(
            selectinload(ParkingLot.cameras),
            selectinload(ParkingLot.spaces),
        )
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
    lot_state = body.state.strip().lower()
    open_hours = normalize_optional_text(body.open_hours) or "24/7"
    owner_name = normalize_optional_text(body.owner_name) or default_owner_name(account)
    payment_link = normalize_optional_text(body.payment_link)
    hourly_rate = 0 if body.is_free else body.hourly_rate
    cameras = [normalize_camera_payload(camera) for camera in body.cameras]

    if not name:
        raise HTTPException(status_code=422, detail="Parking lot name is required")
    if not address:
        raise HTTPException(status_code=422, detail="Parking lot address is required")
    validate_lot_state(lot_state)

    for camera in cameras:
        validate_camera_payload(camera)
    primary_index = primary_camera_index(cameras)

    existing = await db.execute(select(ParkingLot).where(ParkingLot.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Parking lot name already exists")

    lot = ParkingLot(
        name=name,
        address=address,
        latitude=body.latitude,
        longitude=body.longitude,
        state=lot_state,
        owner_name=owner_name,
        hourly_rate=hourly_rate,
        is_free=body.is_free or hourly_rate == 0,
        open_hours=open_hours,
        payment_link=payment_link,
    )
    lot.cameras = [
        ParkingLotCamera(
            name=camera.name,
            camera_type=camera.camera_type,
            stream_url=camera.stream_url,
            is_active=camera.is_active,
            is_primary=index == primary_index,
            created_by_id=account.id,
        )
        for index, camera in enumerate(cameras)
    ]

    db.add(lot)
    await db.commit()

    result = await db.execute(
        select(ParkingLot)
        .options(
            selectinload(ParkingLot.cameras),
            selectinload(ParkingLot.spaces),
        )
        .where(ParkingLot.id == lot.id)
    )
    created_lot = result.scalar_one()
    return lot_response(created_lot)


@router.patch("/lots/{lot_id}", response_model=ParkingLotResponse)
async def update_lot(
    lot_id: int,
    body: ParkingLotUpdate,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    result = await db.execute(
        select(ParkingLot)
        .options(
            selectinload(ParkingLot.cameras),
            selectinload(ParkingLot.spaces),
        )
        .where(ParkingLot.id == lot_id)
    )
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail="Parking lot not found")

    update = body.model_dump(exclude_unset=True)

    if "name" in update:
        name = update["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="Parking lot name is required")
        existing = await db.execute(select(ParkingLot).where(ParkingLot.name == name, ParkingLot.id != lot.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Parking lot name already exists")
        lot.name = name

    if "address" in update:
        address = update["address"].strip()
        if not address:
            raise HTTPException(status_code=422, detail="Parking lot address is required")
        lot.address = address

    if "latitude" in update:
        lot.latitude = update["latitude"]
    if "longitude" in update:
        lot.longitude = update["longitude"]
    if "state" in update:
        lot_state = update["state"].strip().lower()
        validate_lot_state(lot_state)
        lot.state = lot_state
    if "owner_name" in update:
        lot.owner_name = normalize_optional_text(update["owner_name"]) or default_owner_name(account)
    if "hourly_rate" in update:
        lot.hourly_rate = update["hourly_rate"] or 0
        lot.is_free = lot.hourly_rate == 0
    if "is_free" in update:
        lot.is_free = update["is_free"]
        if lot.is_free:
            lot.hourly_rate = 0
    if "open_hours" in update:
        lot.open_hours = normalize_optional_text(update["open_hours"]) or "24/7"
    if "payment_link" in update:
        lot.payment_link = normalize_optional_text(update["payment_link"])

    await db.commit()

    result = await db.execute(
        select(ParkingLot)
        .options(
            selectinload(ParkingLot.cameras),
            selectinload(ParkingLot.spaces),
        )
        .where(ParkingLot.id == lot.id)
    )
    updated_lot = result.scalar_one()
    return lot_response(updated_lot)


@router.delete("/lots/{lot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lot(
    lot_id: int,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)

    lot = await db.get(ParkingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Parking lot not found")

    await db.delete(lot)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    existing_cameras_result = await db.execute(
        select(ParkingLotCamera).where(ParkingLotCamera.parking_lot_id == lot.id)
    )
    existing_cameras = existing_cameras_result.scalars().all()
    is_primary = payload.is_primary or (
        not any(camera.is_primary for camera in existing_cameras)
        and payload.camera_type == "panoramic"
        and payload.is_active
    )

    if is_primary:
        for existing_camera in existing_cameras:
            existing_camera.is_primary = False

    camera = ParkingLotCamera(
        parking_lot_id=lot.id,
        name=payload.name,
        camera_type=payload.camera_type,
        stream_url=payload.stream_url,
        is_active=payload.is_active,
        is_primary=is_primary,
        created_by_id=account.id,
    )
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    return ParkingLotCameraResponse.model_validate(camera)
