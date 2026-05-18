from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import account_response, get_current_account, get_optional_account
from database import get_db
from models import Account, ParkingLot, ParkingLotCamera, ParkingSpace
from schemas import ParkingSpaceCreate, ParkingSpaceResponse, SpacesPageResponse

router = APIRouter(prefix="/api", tags=["parking spaces"])

VALID_STATUSES = {"available", "occupied", "reserved", "out_of_service"}
VALID_SPACE_TYPES = {"normal", "electric", "handicap"}


def normalize_space_payload(body: ParkingSpaceCreate) -> ParkingSpaceCreate:
    return ParkingSpaceCreate(
        parking_lot_id=body.parking_lot_id,
        camera_id=body.camera_id,
        code=body.code.strip().upper(),
        zone=body.zone.strip(),
        level=body.level,
        status=body.status.strip().lower(),
        space_type=body.space_type.strip().lower(),
        is_active=body.is_active,
        latitude=body.latitude,
        longitude=body.longitude,
        polygon=body.polygon,
        bounding_box=body.bounding_box,
    )


def bounding_box_from_polygon(polygon) -> dict[str, float] | None:
    if not polygon:
        return None

    xs = [point[0] for point in polygon.points]
    ys = [point[1] for point in polygon.points]
    min_x = min(xs)
    min_y = min(ys)
    width = max(xs) - min_x
    height = max(ys) - min_y
    if width <= 0 or height <= 0:
        return None
    return {
        "x": min_x,
        "y": min_y,
        "width": width,
        "height": height,
    }


def require_admin(account: Account) -> None:
    if account.role.name not in {"administrator", "municipal", "private"}:
        raise HTTPException(status_code=403, detail="Parking operator access required")


async def resolve_space_links(
    payload: ParkingSpaceCreate,
    db: AsyncSession,
) -> tuple[int | None, int | None]:
    parking_lot_id = payload.parking_lot_id
    camera_id = payload.camera_id

    if parking_lot_id is not None:
        lot = await db.get(ParkingLot, parking_lot_id)
        if not lot:
            raise HTTPException(status_code=404, detail="Parking lot not found")

    if camera_id is not None:
        camera = await db.get(ParkingLotCamera, camera_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Parking lot camera not found")
        if parking_lot_id is not None and camera.parking_lot_id != parking_lot_id:
            raise HTTPException(status_code=422, detail="Camera does not belong to selected parking lot")
        parking_lot_id = parking_lot_id or camera.parking_lot_id

    return parking_lot_id, camera_id


@router.get("/spaces", response_model=SpacesPageResponse)
async def list_spaces(
    response: Response,
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ParkingSpace).order_by(
            ParkingSpace.parking_lot_id.nulls_last(),
            ParkingSpace.zone,
            ParkingSpace.code,
        )
    )
    spaces = result.scalars().all()

    return SpacesPageResponse(
        account=account_response(account) if account else None,
        spaces=[ParkingSpaceResponse.model_validate(space) for space in spaces],
    )


@router.post("/spaces", response_model=ParkingSpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_space(
    body: ParkingSpaceCreate,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_admin(account)
    payload = normalize_space_payload(body)

    if not payload.code:
        raise HTTPException(status_code=422, detail="Space code is required")
    if not payload.zone:
        raise HTTPException(status_code=422, detail="Zone is required")
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid parking space status")
    if payload.space_type not in VALID_SPACE_TYPES:
        raise HTTPException(status_code=422, detail="Invalid parking space type")

    parking_lot_id, camera_id = await resolve_space_links(payload, db)
    bounding_box = (
        payload.bounding_box.model_dump(mode="json")
        if payload.bounding_box
        else bounding_box_from_polygon(payload.polygon)
    )

    existing = await db.execute(select(ParkingSpace).where(ParkingSpace.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Parking space code already exists")

    space = ParkingSpace(
        parking_lot_id=parking_lot_id,
        camera_id=camera_id,
        code=payload.code,
        zone=payload.zone,
        level=payload.level,
        status=payload.status,
        space_type=payload.space_type,
        is_active=payload.is_active,
        latitude=payload.latitude,
        longitude=payload.longitude,
        polygon=payload.polygon.model_dump(mode="json") if payload.polygon else None,
        bounding_box=bounding_box,
        created_by_id=account.id,
    )
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return ParkingSpaceResponse.model_validate(space)
