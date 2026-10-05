from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from database import async_session
from models import SecurityKey

router = APIRouter(prefix="/api/gate", tags=["gate"])

GATE_COOKIE_NAME = "parkflow_gate"
GATE_SESSION_HOURS = 12  # ponytail: in-memory sessions, restart requires re-entering the key

# loaded once at startup from security_keys table; SQL changes need a restart
_key_hashes: set[str] = set()
_gate_sessions: dict[str, datetime] = {}


def _hash_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


async def load_gate_keys() -> None:
    async with async_session() as db:
        result = await db.execute(select(SecurityKey.key_hash).where(SecurityKey.is_active))
        _key_hashes.clear()
        _key_hashes.update(result.scalars())


def gate_enabled() -> bool:
    return bool(_key_hashes)


def _prune_gate_sessions() -> None:
    now = datetime.now(timezone.utc)
    for token in [t for t, expires in _gate_sessions.items() if expires <= now]:
        _gate_sessions.pop(token, None)


def gate_passed(token: str | None) -> bool:
    if not gate_enabled():
        return True
    _prune_gate_sessions()
    return bool(token and token in _gate_sessions)


class GateVerifyRequest(BaseModel):
    key: str


@router.get("/status")
def gate_status(gate_token: str | None = Cookie(default=None, alias=GATE_COOKIE_NAME)):
    return {"passed": gate_passed(gate_token)}


@router.post("/verify")
async def gate_verify(response: Response, body: GateVerifyRequest):
    if not gate_enabled():
        raise HTTPException(status_code=409, detail="No security keys configured")
    if _hash_key(body.key) not in _key_hashes:
        raise HTTPException(status_code=401, detail="Invalid security key")
    token = secrets.token_urlsafe(32)
    _gate_sessions[token] = datetime.now(timezone.utc) + timedelta(hours=GATE_SESSION_HOURS)
    response.set_cookie(
        key=GATE_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=GATE_SESSION_HOURS * 60 * 60,
        path="/",
    )
    return {"passed": True}


class GateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not path.startswith("/api/gate/"):
            if not gate_passed(request.cookies.get(GATE_COOKIE_NAME)):
                return JSONResponse({"detail": "Security key required"}, status_code=401)
        return await call_next(request)
