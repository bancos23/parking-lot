from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from passlib.context import CryptContext
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models import Account, AccountSession, Organisation, OrganisationMembership, UserRole
from schemas import AccountOrganisationResponse, AccountResponse, LoginRequest, MessageResponse, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE_NAME = "parkflow_session"


def hash_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def account_response(account: Account) -> AccountResponse:
    role_name = "municipal" if account.role.name == "administrator" else account.role.name
    memberships = sorted(
        account.organisation_memberships,
        key=lambda membership: membership.organisation.name.lower(),
    )
    return AccountResponse(
        id=account.id,
        email=account.email,
        name=account.name,
        phone=account.phone,
        role=role_name,
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
    )


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_optional(value: str | None) -> str | None:
    normalized = " ".join(value.strip().split()) if value else ""
    return normalized or None


def normalize_organisation_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalized_organisation_key(value: str) -> str:
    return normalize_organisation_name(value).casefold()


def account_context_options():
    return (
        selectinload(Account.role),
        selectinload(Account.organisation_memberships).selectinload(OrganisationMembership.organisation),
    )


async def load_account_context(db: AsyncSession, account_id: int) -> Account | None:
    result = await db.execute(
        select(Account)
        .options(*account_context_options())
        .where(Account.id == account_id)
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

    role = await get_or_create_role(db, body.role)

    account = Account(
        email=body.email,
        password=pwd_context.hash(body.password),
        name=name,
        phone=normalize_optional(body.phone),
        role_id=role.id,
    )
    db.add(account)
    await db.flush()

    if body.role == "private":
        organisation, created = await get_or_create_organisation(
            db,
            body.organisation_name or "",
            account.id,
        )
        db.add(
            OrganisationMembership(
                account_id=account.id,
                organisation_id=organisation.id,
                membership_role="owner" if created else "associate",
            )
        )

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
