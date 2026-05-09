from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from passlib.context import CryptContext
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import Account, AccountSession, UserRole
from schemas import AccountResponse, LoginRequest, MessageResponse, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE_NAME = "parkflow_session"


def hash_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def account_response(account: Account) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        email=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        role=account.role.name,
    )


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


async def get_current_account(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> Account:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_hash = hash_session_token(session_token)
    session_result = await db.execute(
        select(AccountSession.account_id)
        .where(AccountSession.token_hash == token_hash)
        .where(AccountSession.expires_at > datetime.now(timezone.utc))
    )
    account_id = session_result.scalar_one_or_none()
    if not account_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=401, detail="Invalid session account")

    await db.execute(
        update(AccountSession)
        .where(AccountSession.token_hash == token_hash)
        .values(expires_at=new_session_expiration())
    )
    await db.commit()
    set_session_cookie(response, session_token)

    await db.refresh(account, attribute_names=["role"])
    return account


async def get_or_create_role(db: AsyncSession, name: str) -> UserRole:
    result = await db.execute(select(UserRole).where(UserRole.name == name))
    role = result.scalar_one_or_none()
    if not role:
        role = UserRole(name=name)
        db.add(role)
        await db.flush()
    return role


@router.post("/register", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Account).where(Account.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    role = await get_or_create_role(db, "guest")

    account = Account(
        email=body.email,
        password=pwd_context.hash(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role_id=role.id,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    await db.refresh(account, attribute_names=["role"])
    return account_response(account)


@router.post("/login", response_model=AccountResponse)
async def login(response: Response, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.email == body.email))
    account = result.scalar_one_or_none()

    if not account or not pwd_context.verify(body.password, account.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token, _ = await create_session(db, account)
    set_session_cookie(response, token)
    await db.refresh(account, attribute_names=["role"])
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
