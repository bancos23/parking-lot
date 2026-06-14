from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import delete, select, text

from auth import get_optional_account, router as auth_router
from database import engine, async_session, Base
from detections import (
    router as detections_router,
    start_occupancy_detection_scheduler,
    stop_occupancy_detection_scheduler,
)
from lots import router as lots_router
from models import Account, AccountSession, UserRole
from spaces import router as spaces_router
from plates import router as plates_router, warm_up_plate_ocr

DEFAULT_ROLES = ["municipal", "private", "guest", "administrator"]

SCHEMA_UPGRADE_STATEMENTS = [
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS name VARCHAR(200)",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'accounts'
          AND column_name = 'first_name'
      ) AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'accounts'
          AND column_name = 'last_name'
      ) THEN
        UPDATE accounts
        SET name = trim(concat_ws(' ', first_name, last_name))
        WHERE name IS NULL;
      END IF;
    END $$;
    """,
    "UPDATE accounts SET name = email WHERE name IS NULL",
    "ALTER TABLE accounts ALTER COLUMN name SET NOT NULL",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS phone VARCHAR(30)",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'accounts'
          AND column_name = 'first_name'
      ) THEN
        ALTER TABLE accounts ALTER COLUMN first_name DROP NOT NULL;
      END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'accounts'
          AND column_name = 'last_name'
      ) THEN
        ALTER TABLE accounts ALTER COLUMN last_name DROP NOT NULL;
      END IF;
    END $$;
    """,
    "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS normalized_name VARCHAR(255)",
    "UPDATE organisations SET normalized_name = lower(regexp_replace(trim(name), '\\s+', ' ', 'g')) WHERE normalized_name IS NULL",
    "ALTER TABLE organisations ALTER COLUMN normalized_name SET NOT NULL",
    "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS organisation_type VARCHAR(50) DEFAULT 'parking_operator'",
    "UPDATE organisations SET organisation_type = 'parking_operator' WHERE organisation_type IS NULL",
    "ALTER TABLE organisations ALTER COLUMN organisation_type SET NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_organisations_normalized_name ON organisations (normalized_name)",
    "ALTER TABLE organisation_memberships ADD COLUMN IF NOT EXISTS membership_role VARCHAR(30) DEFAULT 'associate'",
    "UPDATE organisation_memberships SET membership_role = 'associate' WHERE membership_role IS NULL",
    "ALTER TABLE organisation_memberships ALTER COLUMN membership_role SET NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_organisation_memberships_account_organisation ON organisation_memberships (account_id, organisation_id)",
    "ALTER TABLE parking_lot_cameras DROP COLUMN IF EXISTS calibration_json_url",
    "ALTER TABLE parking_lot_cameras ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
    "UPDATE parking_lot_cameras SET is_active = TRUE WHERE is_active IS NULL",
    "ALTER TABLE parking_lot_cameras ALTER COLUMN is_active SET NOT NULL",
    "ALTER TABLE parking_lot_cameras ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT FALSE",
    "UPDATE parking_lot_cameras SET is_primary = FALSE WHERE is_primary IS NULL",
    "ALTER TABLE parking_lot_cameras ALTER COLUMN is_primary SET NOT NULL",
    "ALTER TABLE parking_lot_cameras DROP COLUMN IF EXISTS latitude",
    "ALTER TABLE parking_lot_cameras DROP COLUMN IF EXISTS longitude",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
    "ALTER TABLE parking_lots DROP COLUMN IF EXISTS lot_type",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS state VARCHAR(30) DEFAULT 'enabled'",
    "UPDATE parking_lots SET state = 'enabled' WHERE state IS NULL",
    "ALTER TABLE parking_lots ALTER COLUMN state SET NOT NULL",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS owner_name VARCHAR(255)",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'parking_lots'
          AND column_name = 'created_by_id'
      ) THEN
        UPDATE parking_lots
        SET owner_name = CASE
          WHEN user_roles.name IN ('administrator', 'municipal') THEN 'Primăria Baia Mare'
          ELSE accounts.name
        END
        FROM accounts
        JOIN user_roles ON user_roles.id = accounts.role_id
        WHERE parking_lots.created_by_id = accounts.id
          AND (parking_lots.owner_name IS NULL OR trim(parking_lots.owner_name) = '');
      END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'parking_lots'
          AND column_name = 'owner_organisation_id'
      ) THEN
        UPDATE parking_lots
        SET owner_name = organisations.name
        FROM organisations
        WHERE parking_lots.owner_organisation_id = organisations.id
          AND (parking_lots.owner_name IS NULL OR trim(parking_lots.owner_name) = '');
      END IF;
    END $$;
    """,
    "DROP INDEX IF EXISTS ix_parking_lots_owner_organisation_id",
    "ALTER TABLE parking_lots DROP COLUMN IF EXISTS owner_organisation_id",
    "ALTER TABLE parking_lots DROP COLUMN IF EXISTS created_by_id",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS hourly_rate DOUBLE PRECISION DEFAULT 0",
    "UPDATE parking_lots SET hourly_rate = 0 WHERE hourly_rate IS NULL",
    "ALTER TABLE parking_lots ALTER COLUMN hourly_rate SET NOT NULL",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS is_free BOOLEAN DEFAULT FALSE",
    "UPDATE parking_lots SET is_free = FALSE WHERE is_free IS NULL",
    "ALTER TABLE parking_lots ALTER COLUMN is_free SET NOT NULL",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS open_hours VARCHAR(100) DEFAULT '24/7'",
    "UPDATE parking_lots SET open_hours = '24/7' WHERE open_hours IS NULL",
    "ALTER TABLE parking_lots ALTER COLUMN open_hours SET NOT NULL",
    "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS payment_link VARCHAR(500)",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS parking_lot_id INTEGER REFERENCES parking_lots(id)",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS camera_id INTEGER REFERENCES parking_lot_cameras(id)",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT 0",
    "ALTER TABLE parking_spaces ALTER COLUMN level DROP DEFAULT",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'parking_spaces'
          AND column_name = 'level'
          AND data_type IN ('character varying', 'text')
      ) THEN
        ALTER TABLE parking_spaces
        ALTER COLUMN level TYPE INTEGER
        USING CASE
          WHEN trim(level::text) ~ '^-?[0-9]+$' THEN trim(level::text)::integer
          WHEN lower(trim(level::text)) = 'ground' THEN 0
          WHEN level IS NULL OR trim(level::text) = '' THEN 0
          ELSE 0
        END;
      END IF;
    END $$;
    """,
    "UPDATE parking_spaces SET level = 0 WHERE level IS NULL",
    "ALTER TABLE parking_spaces ALTER COLUMN level SET DEFAULT 0",
    "ALTER TABLE parking_spaces ALTER COLUMN level SET NOT NULL",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS space_type VARCHAR(30) DEFAULT 'normal'",
    "UPDATE parking_spaces SET space_type = 'normal' WHERE space_type IS NULL",
    "UPDATE parking_spaces SET space_type = 'electric' WHERE space_type = 'charging_station'",
    "ALTER TABLE parking_spaces ALTER COLUMN space_type SET NOT NULL",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
    "UPDATE parking_spaces SET is_active = TRUE WHERE is_active IS NULL",
    "ALTER TABLE parking_spaces ALTER COLUMN is_active SET NOT NULL",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS polygon JSONB",
    "ALTER TABLE parking_spaces ADD COLUMN IF NOT EXISTS bounding_box JSONB",
    "CREATE INDEX IF NOT EXISTS ix_parking_spaces_parking_lot_id ON parking_spaces (parking_lot_id)",
    "CREATE INDEX IF NOT EXISTS ix_parking_spaces_camera_id ON parking_spaces (camera_id)",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'parking_lots'
          AND column_name = 'total_spots'
      ) THEN
        INSERT INTO parking_spaces (
          parking_lot_id,
          code,
          zone,
          level,
          status,
          space_type,
          is_active
        )
        SELECT
          lot.id,
          concat('L', lot.id, '-', lpad(series.space_number::text, 3, '0')),
          'General',
          0,
          'available',
          'normal',
          TRUE
        FROM parking_lots lot
        CROSS JOIN LATERAL (
          SELECT count(*)::integer AS existing_spaces
          FROM parking_spaces existing
          WHERE existing.parking_lot_id = lot.id
        ) existing_count
        JOIN LATERAL generate_series(existing_count.existing_spaces + 1, COALESCE(lot.total_spots, 0)) AS series(space_number)
          ON COALESCE(lot.total_spots, 0) > existing_count.existing_spaces
        ON CONFLICT (code) DO NOTHING;
      END IF;
    END $$;
    """,
    "ALTER TABLE parking_lots DROP COLUMN IF EXISTS total_spots",
    """
    CREATE TABLE IF NOT EXISTS parking_space_detections (
        id SERIAL PRIMARY KEY,
        parking_lot_id INTEGER NOT NULL REFERENCES parking_lots(id),
        camera_id INTEGER NOT NULL REFERENCES parking_lot_cameras(id),
        parking_space_id INTEGER REFERENCES parking_spaces(id),
        space_code VARCHAR(30),
        previous_status VARCHAR(30),
        status VARCHAR(30) NOT NULL,
        occupied BOOLEAN NOT NULL,
        confidence DOUBLE PRECISION,
        match_iou DOUBLE PRECISION,
        bounding_box JSONB,
        polygon JSONB,
        raw_detection JSONB,
        source VARCHAR(120),
        detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
        received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_parking_space_detections_parking_lot_id ON parking_space_detections (parking_lot_id)",
    "CREATE INDEX IF NOT EXISTS ix_parking_space_detections_camera_id ON parking_space_detections (camera_id)",
    "CREATE INDEX IF NOT EXISTS ix_parking_space_detections_parking_space_id ON parking_space_detections (parking_space_id)",
    "CREATE INDEX IF NOT EXISTS ix_parking_space_detections_space_code ON parking_space_detections (space_code)",
    "CREATE INDEX IF NOT EXISTS ix_parking_space_detections_detected_at ON parking_space_detections (detected_at)",
    """
    CREATE TABLE IF NOT EXISTS license_plate_detection_history (
        id SERIAL PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        source_file VARCHAR(255),
        image_width INTEGER,
        image_height INTEGER,
        model VARCHAR(120),
        detection_confidence DOUBLE PRECISION,
        total_detections INTEGER DEFAULT 0 NOT NULL,
        parsed_plates INTEGER DEFAULT 0 NOT NULL,
        plate VARCHAR(40),
        compact VARCHAR(30),
        county_code VARCHAR(10),
        county_name VARCHAR(120),
        country_code VARCHAR(10),
        country_name VARCHAR(120),
        plate_type VARCHAR(30),
        raw_ocr VARCHAR(120),
        confidence DOUBLE PRECISION,
        bounding_box JSONB,
        raw_detection JSONB,
        detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_license_plate_detection_history_account_id ON license_plate_detection_history (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_license_plate_detection_history_plate ON license_plate_detection_history (plate)",
    "CREATE INDEX IF NOT EXISTS ix_license_plate_detection_history_compact ON license_plate_detection_history (compact)",
    "CREATE INDEX IF NOT EXISTS ix_license_plate_detection_history_country_code ON license_plate_detection_history (country_code)",
    "CREATE INDEX IF NOT EXISTS ix_license_plate_detection_history_detected_at ON license_plate_detection_history (detected_at)",
]


async def ensure_schema_upgrades(conn) -> None:
    for statement in SCHEMA_UPGRADE_STATEMENTS:
        await conn.execute(text(statement))


async def clear_startup_sessions() -> None:
    async with async_session() as db:
        await db.execute(delete(AccountSession))
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_schema_upgrades(conn)
    await clear_startup_sessions()
    warm_up_plate_ocr()
    async with async_session() as db:
        for role_name in DEFAULT_ROLES:
            exists = await db.execute(select(UserRole).where(UserRole.name == role_name))
            if not exists.scalar_one_or_none():
                db.add(UserRole(name=role_name))
        await db.commit()

    occupancy_detection_task = start_occupancy_detection_scheduler(async_session)
    try:
        yield
    finally:
        await stop_occupancy_detection_scheduler(occupancy_detection_task)
        await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
	CORSMiddleware,
	allow_origins=["http://localhost:5173"],
	allow_origin_regex=r"https?://.*:5173",
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"]
)

app.include_router(auth_router)
app.include_router(lots_router)
app.include_router(spaces_router)
app.include_router(detections_router)
app.include_router(plates_router)

@app.get("/api/test")
def read_root():
	return {"message": "Test!"}


@app.get("/api/dashboard")
def dashboard(account: Account | None = Depends(get_optional_account)):
	return {
		"account": {
			"id": account.id,
			"email": account.email,
			"name": account.name,
			"phone": account.phone,
			"role": "municipal" if account.role.name == "administrator" else account.role.name,
		} if account else None,
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
