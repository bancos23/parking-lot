from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select

from auth import get_current_account, router as auth_router
from database import engine, async_session, Base
from models import Account, UserRole

DEFAULT_ROLES = ["administrator", "guest"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        for role_name in DEFAULT_ROLES:
            exists = await db.execute(select(UserRole).where(UserRole.name == role_name))
            if not exists.scalar_one_or_none():
                db.add(UserRole(name=role_name))
        await db.commit()
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
	CORSMiddleware,
	allow_origins=["http://localhost:5173"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"]
)

app.include_router(auth_router)

@app.get("/api/test")
def read_root():
	return {"message": "Test!"}


@app.get("/api/dashboard")
def dashboard(account: Account = Depends(get_current_account)):
	return {
		"account": {
			"id": account.id,
			"email": account.email,
			"firstName": account.first_name,
			"lastName": account.last_name,
		},
		"stats": {
			"totalSpots": 128,
			"occupiedSpots": 110,
			"availableSpots": 18,
			"todayRevenue": 1240,
			"activeVehicles": 110,
			"pendingPayments": 7,
		},
		"recentVehicles": [
			{"plate": "B 123 ABC", "spot": "A-14", "entryTime": "09:24", "status": "Parked", "payment": "Paid"},
			{"plate": "CJ 88 KLM", "spot": "B-07", "entryTime": "10:12", "status": "Parked", "payment": "Pending"},
			{"plate": "TM 45 RST", "spot": "C-22", "entryTime": "11:03", "status": "Parked", "payment": "Paid"},
			{"plate": "BV 19 ZYX", "spot": "D-02", "entryTime": "11:41", "status": "Parked", "payment": "Pending"},
		],
		"parkingZones": [
			{"name": "Zone A", "total": 32, "occupied": 28},
			{"name": "Zone B", "total": 40, "occupied": 35},
			{"name": "Zone C", "total": 36, "occupied": 29},
			{"name": "Zone D", "total": 20, "occupied": 18},
		],
	}
