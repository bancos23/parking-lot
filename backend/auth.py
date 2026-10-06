from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from passlib.context import CryptContext
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models import (
    Account,
    AccountLicensePlate,
    AccountSession,
    LicensePlateDetectionHistory,
    Organisation,
    OrganisationMembership,
    UserRole,
)
from schemas import (
    AccountLicensePlateCreate,
    AccountLicensePlateResponse,
    AccountOrganisationResponse,
    AccountResponse,
    AccountUpdateRequest,
    AccountPasswordUpdateRequest,
    CurrentPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE_NAME = "parkflow_session"
REGISTERED_USER_ROLE = "user"
PARKING_MANAGER_ROLES = {"administrator", "municipal", "private"}
CAMERA_VIEWER_ROLES = {*PARKING_MANAGER_ROLES, REGISTERED_USER_ROLE}
ACCOUNT_SETTINGS_ROLES = {"administrator", REGISTERED_USER_ROLE}


def hash_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def has_management_access(account: Account | None) -> bool:
    return bool(account and account.role.name in PARKING_MANAGER_ROLES)


def require_management_access(account: Account) -> None:
    if not has_management_access(account):
        raise HTTPException(status_code=403, detail="Parking management access required")


def has_camera_access(account: Account | None) -> bool:
    return bool(account and account.role.name in CAMERA_VIEWER_ROLES)


def require_camera_access(account: Account) -> None:
    if not has_camera_access(account):
        raise HTTPException(status_code=403, detail="Camera access required")


def require_user_access(account: Account) -> None:
    if account.role.name not in ACCOUNT_SETTINGS_ROLES:
        raise HTTPException(status_code=403, detail="Account settings access required")


def account_response(account: Account) -> AccountResponse:
    memberships = sorted(
        account.organisation_memberships,
        key=lambda membership: membership.organisation.name.lower(),
    )
    return AccountResponse(
        id=account.id,
        email=account.email,
        name=account.name,
        phone=account.phone,
        birth_date=account.birth_date,
        city=account.city,
        role=account.role.name,
        organisations=[
            AccountOrganisationResponse(
                id=membership.organisation.id,
                name=membership.organisation.name,
                organisation_type=membership.organisation.organisation_type,
                membership_role=membership.membership_role,
            )
            for membership in memberships
            if membership.deleted_at is None and membership.organisation.deleted_at is None
        ],
        license_plates=[
            AccountLicensePlateResponse.model_validate(plate)
            for plate in sorted(account.license_plates, key=lambda plate: (not plate.is_active, plate.id))
        ],
    )


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_optional(value: str | None) -> str | None:
    normalized = " ".join(value.strip().split()) if value else ""
    return normalized or None


def normalize_license_plate(value: str) -> tuple[str, str]:
    plate_number = " ".join(value.strip().upper().split())
    normalized_plate = re.sub(r"[\s-]+", "", plate_number)
    if not re.fullmatch(r"[A-Z0-9]{3,15}", normalized_plate):
        raise HTTPException(status_code=422, detail="Invalid license plate number")
    return plate_number, normalized_plate


def normalize_organisation_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalized_organisation_key(value: str) -> str:
    return normalize_organisation_name(value).casefold()


def account_context_options():
    return (
        selectinload(Account.role),
        selectinload(Account.license_plates),
        selectinload(Account.organisation_memberships).selectinload(OrganisationMembership.organisation),
    )


async def load_account_context(db: AsyncSession, account_id: int) -> Account | None:
    result = await db.execute(
        select(Account)
        .options(*account_context_options())
        .where(Account.id == account_id)
        .where(Account.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


def new_session_expiration() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        minutes=settings.session_idle_timeout_minutes
    )


async def create_session(db: AsyncSession, account: Account) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = new_session_expiration()
    db.add(
        AccountSession(
            token_hash=hash_session_token(token),
            account_id=account.id,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return token, expires_at


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_cookie_max_age_days * 24 * 60 * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="lax")


def clear_session_cookie_header() -> str:
    return f'{SESSION_COOKIE_NAME}=""; Max-Age=0; Path=/; SameSite=lax'


def authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"Set-Cookie": clear_session_cookie_header()},
    )


async def destroy_session(db: AsyncSession, token_hash: str) -> None:
    await db.execute(delete(AccountSession).where(AccountSession.token_hash == token_hash))
    await db.commit()


async def get_current_account(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> Account:
    if not session_token:
        clear_session_cookie(response)
        raise authentication_error("Not authenticated")

    token_hash = hash_session_token(session_token)
    session_result = await db.execute(
        select(AccountSession.account_id)
        .where(AccountSession.token_hash == token_hash)
        .where(AccountSession.expires_at > datetime.now(timezone.utc))
    )
    account_id = session_result.scalar_one_or_none()
    if not account_id:
        await destroy_session(db, token_hash)
        clear_session_cookie(response)
        raise authentication_error("Invalid or expired session")

    account = await load_account_context(db, account_id)
    if not account:
        await destroy_session(db, token_hash)
        clear_session_cookie(response)
        raise authentication_error("Invalid session account")

    await db.execute(
        update(AccountSession)
        .where(AccountSession.token_hash == token_hash)
        .values(expires_at=new_session_expiration())
    )
    await db.commit()
    set_session_cookie(response, session_token)

    return account


async def get_optional_account(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> Account | None:
    if not session_token:
        return None

    token_hash = hash_session_token(session_token)
    session_result = await db.execute(
        select(AccountSession.account_id)
        .where(AccountSession.token_hash == token_hash)
        .where(AccountSession.expires_at > datetime.now(timezone.utc))
    )
    account_id = session_result.scalar_one_or_none()
    if not account_id:
        await destroy_session(db, token_hash)
        clear_session_cookie(response)
        return None

    account = await load_account_context(db, account_id)
    if not account:
        await destroy_session(db, token_hash)
        clear_session_cookie(response)
        return None

    await db.execute(
        update(AccountSession)
        .where(AccountSession.token_hash == token_hash)
        .values(expires_at=new_session_expiration())
    )
    await db.commit()
    set_session_cookie(response, session_token)

    return account


async def get_or_create_role(db: AsyncSession, name: str) -> UserRole:
    result = await db.execute(select(UserRole).where(UserRole.name == name))
    role = result.scalar_one_or_none()
    if not role:
        role = UserRole(name=name)
        db.add(role)
        await db.flush()
    return role


async def get_or_create_organisation(
    db: AsyncSession,
    name: str,
    created_by_id: int,
) -> tuple[Organisation, bool]:
    organization_name = normalize_organisation_name(name)
    normalized_name = normalized_organisation_key(name)
    result = await db.execute(
        select(Organisation).where(Organisation.normalized_name == normalized_name)
    )
    organisation = result.scalar_one_or_none()
    if organisation:
        return organisation, False

    organisation = Organisation(
        name=organization_name,
        normalized_name=normalized_name,
        organisation_type="parking_operator",
        created_by_id=created_by_id,
    )
    db.add(organisation)
    await db.flush()
    return organisation, True


@router.post("/register", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def register(response: Response, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Account).where(Account.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    name = normalize_name(body.name)
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")

    role = await get_or_create_role(db, REGISTERED_USER_ROLE)

    account = Account(
        email=body.email,
        password=pwd_context.hash(body.password),
        name=name,
        phone=normalize_optional(body.phone),
        role_id=role.id,
    )
    db.add(account)
    await db.commit()

    account_with_context = await load_account_context(db, account.id)
    if not account_with_context:
        raise HTTPException(status_code=500, detail="Registered account could not be loaded")
    token, _ = await create_session(db, account_with_context)
    set_session_cookie(response, token)
    return account_response(account_with_context)


@router.post("/login", response_model=AccountResponse)
async def login(response: Response, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Account)
        .options(*account_context_options())
        .where(Account.email == body.email)
        .where(Account.deleted_at.is_(None))
    )
    account = result.scalar_one_or_none()

    if not account or not pwd_context.verify(body.password, account.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token, _ = await create_session(db, account)
    set_session_cookie(response, token)
    return account_response(account)


@router.get("/me", response_model=AccountResponse)
async def me(account: Account = Depends(get_current_account)):
    return account_response(account)


async def refreshed_account_response(db: AsyncSession, account_id: int) -> AccountResponse:
    account = await load_account_context(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account_response(account)


@router.patch("/me", response_model=AccountResponse)
async def update_me(
    body: AccountUpdateRequest,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_user_access(account)
    name = normalize_name(body.name)
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")

    email = str(body.email)
    existing = await db.execute(
        select(Account.id)
        .where(Account.email == email)
        .where(Account.id != account.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    account.email = email
    account.name = name
    account.phone = normalize_optional(body.phone)
    account.birth_date = body.birth_date
    account.city = normalize_optional(body.city)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    return await refreshed_account_response(db, account.id)


@router.delete("/me", response_model=MessageResponse)
async def delete_me(
    response: Response,
    body: CurrentPasswordRequest,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_user_access(account)
    if not pwd_context.verify(body.password, account.password):
        raise HTTPException(status_code=400, detail="Incorrect password")

    await db.execute(delete(AccountSession).where(AccountSession.account_id == account.id))
    await db.execute(delete(AccountLicensePlate).where(AccountLicensePlate.account_id == account.id))
    await db.execute(
        delete(LicensePlateDetectionHistory).where(
            LicensePlateDetectionHistory.account_id == account.id
        )
    )
    await db.execute(
        delete(OrganisationMembership).where(OrganisationMembership.account_id == account.id)
    )

    account.email = f"deleted-{account.id}@deleted.invalid"
    account.password = pwd_context.hash(secrets.token_urlsafe(32))
    account.name = "Cont șters"
    account.phone = None
    account.birth_date = None
    account.city = None
    account.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    clear_session_cookie(response)
    return MessageResponse(message="Account deleted")


@router.post("/me/password/verify", response_model=MessageResponse)
async def verify_current_password(
    body: CurrentPasswordRequest,
    account: Account = Depends(get_current_account),
):
    require_user_access(account)
    if not pwd_context.verify(body.password, account.password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    return MessageResponse(message="Password verified")


@router.patch("/me/password", response_model=MessageResponse)
async def change_password(
    response: Response,
    body: AccountPasswordUpdateRequest,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_user_access(account)
    if not pwd_context.verify(body.current_password, account.password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    if pwd_context.verify(body.new_password, account.password):
        raise HTTPException(status_code=400, detail="New password must be different")

    account.password = pwd_context.hash(body.new_password)
    await db.execute(delete(AccountSession).where(AccountSession.account_id == account.id))
    await db.commit()

    clear_session_cookie(response)
    return MessageResponse(message="Password changed")


@router.post("/me/license-plates", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def add_license_plate(
    body: AccountLicensePlateCreate,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_user_access(account)
    plate_number, normalized_plate = normalize_license_plate(body.plate_number)
    existing = await db.execute(
        select(AccountLicensePlate.id)
        .where(AccountLicensePlate.account_id == account.id)
        .where(AccountLicensePlate.normalized_plate == normalized_plate)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="License plate already registered")

    active = await db.execute(
        select(AccountLicensePlate.id)
        .where(AccountLicensePlate.account_id == account.id)
        .where(AccountLicensePlate.is_active.is_(True))
        .limit(1)
    )
    db.add(
        AccountLicensePlate(
            account_id=account.id,
            plate_number=plate_number,
            normalized_plate=normalized_plate,
            is_active=active.scalar_one_or_none() is None,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="License plate already registered")

    return await refreshed_account_response(db, account.id)


@router.patch("/me/license-plates/{plate_id}/activate", response_model=AccountResponse)
async def activate_license_plate(
    plate_id: int,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_user_access(account)
    result = await db.execute(
        select(AccountLicensePlate)
        .where(AccountLicensePlate.id == plate_id)
        .where(AccountLicensePlate.account_id == account.id)
    )
    plate = result.scalar_one_or_none()
    if not plate:
        raise HTTPException(status_code=404, detail="License plate not found")

    await db.execute(
        update(AccountLicensePlate)
        .where(AccountLicensePlate.account_id == account.id)
        .values(is_active=False)
    )
    plate.is_active = True
    await db.commit()
    return await refreshed_account_response(db, account.id)


@router.delete("/me/license-plates/{plate_id}", response_model=AccountResponse)
async def delete_license_plate(
    plate_id: int,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    require_user_access(account)
    result = await db.execute(
        select(AccountLicensePlate)
        .where(AccountLicensePlate.id == plate_id)
        .where(AccountLicensePlate.account_id == account.id)
    )
    plate = result.scalar_one_or_none()
    if not plate:
        raise HTTPException(status_code=404, detail="License plate not found")

    was_active = plate.is_active
    await db.delete(plate)
    await db.flush()
    if was_active:
        replacement = await db.execute(
            select(AccountLicensePlate)
            .where(AccountLicensePlate.account_id == account.id)
            .order_by(AccountLicensePlate.id)
            .limit(1)
        )
        next_plate = replacement.scalar_one_or_none()
        if next_plate:
            next_plate.is_active = True

    await db.commit()
    return await refreshed_account_response(db, account.id)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    if session_token:
        await db.execute(
            delete(AccountSession).where(
                AccountSession.token_hash == hash_session_token(session_token)
            )
        )
        await db.commit()

    clear_session_cookie(response)
    return MessageResponse(message="Logged out")
