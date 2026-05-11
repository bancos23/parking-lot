from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import account_response, get_current_account, get_optional_account
from database import get_db
from models import Account, ParkingSpace
from schemas import ParkingSpaceCreate, ParkingSpaceResponse, SpacesPageResponse

router = APIRouter(prefix="/api", tags=["parking spaces"])

VALID_STATUSES = {"available", "occupied", "reserved", "out_of_service"}


def normalize_space_payload(body: ParkingSpaceCreate) -> ParkingSpaceCreate:
    return ParkingSpaceCreate(
        code=body.code.strip().upper(),
        zone=body.zone.strip(),
        level=body.level.strip() or "Ground",
        status=body.status.strip().lower(),
    )


def require_admin(account: Account) -> None:
    if account.role.name != "administrator":
        raise HTTPException(status_code=403, detail="Administrator access required")


@router.get("/spaces", response_model=SpacesPageResponse)
async def list_spaces(
    response: Response,
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ParkingSpace).order_by(ParkingSpace.zone, ParkingSpace.code))
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

    existing = await db.execute(select(ParkingSpace).where(ParkingSpace.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Parking space code already exists")

    space = ParkingSpace(
        code=payload.code,
        zone=payload.zone,
        level=payload.level,
        status=payload.status,
        created_by_id=account.id,
    )
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return ParkingSpaceResponse.model_validate(space)
