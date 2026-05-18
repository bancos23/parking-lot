from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="role")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("user_roles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped["UserRole"] = relationship(back_populates="accounts")
    sessions: Mapped[list["AccountSession"]] = relationship(back_populates="account")
    organisation_memberships: Mapped[list["OrganisationMembership"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    created_parking_cameras: Mapped[list["ParkingLotCamera"]] = relationship(back_populates="created_by")


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped["Account"] = relationship(back_populates="sessions")


class Organisation(Base):
    __tablename__ = "organisations"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_organisations_normalized_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    organisation_type: Mapped[str] = mapped_column(String(50), default="parking_operator", nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[Optional["Account"]] = relationship(foreign_keys=[created_by_id])
    memberships: Mapped[list["OrganisationMembership"]] = relationship(
        back_populates="organisation",
        cascade="all, delete-orphan",
    )


class OrganisationMembership(Base):
    __tablename__ = "organisation_memberships"
    __table_args__ = (
        UniqueConstraint("account_id", "organisation_id", name="uq_organisation_memberships_account_organisation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False, index=True)
    membership_role: Mapped[str] = mapped_column(String(30), default="associate", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="organisation_memberships")
    organisation: Mapped["Organisation"] = relationship(back_populates="memberships")


class ParkingSpace(Base):
    __tablename__ = "parking_spaces"
    __table_args__ = (UniqueConstraint("code", name="uq_parking_spaces_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_lot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("parking_lots.id"), nullable=True, index=True)
    camera_id: Mapped[Optional[int]] = mapped_column(ForeignKey("parking_lot_cameras.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    zone: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    space_type: Mapped[str] = mapped_column(String(30), default="normal", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    polygon: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    bounding_box: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parking_lot: Mapped[Optional["ParkingLot"]] = relationship(back_populates="spaces")
    camera: Mapped[Optional["ParkingLotCamera"]] = relationship(back_populates="spaces")
    detections: Mapped[list["ParkingSpaceDetection"]] = relationship(back_populates="space")


class ParkingLot(Base):
    __tablename__ = "parking_lots"
    __table_args__ = (UniqueConstraint("name", name="uq_parking_lots_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False)
    owner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hourly_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_hours: Mapped[str] = mapped_column(String(100), default="24/7", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cameras: Mapped[list["ParkingLotCamera"]] = relationship(
        back_populates="parking_lot",
        cascade="all, delete-orphan",
    )
    spaces: Mapped[list["ParkingSpace"]] = relationship(back_populates="parking_lot")
    detections: Mapped[list["ParkingSpaceDetection"]] = relationship(back_populates="parking_lot")


class ParkingLotCamera(Base):
    __tablename__ = "parking_lot_cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_lot_id: Mapped[int] = mapped_column(ForeignKey("parking_lots.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    camera_type: Mapped[str] = mapped_column(String(30), nullable=False)
    stream_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parking_lot: Mapped["ParkingLot"] = relationship(back_populates="cameras")
    created_by: Mapped[Optional["Account"]] = relationship(back_populates="created_parking_cameras")
    spaces: Mapped[list["ParkingSpace"]] = relationship(back_populates="camera")
    detections: Mapped[list["ParkingSpaceDetection"]] = relationship(back_populates="camera")


class ParkingSpaceDetection(Base):
    __tablename__ = "parking_space_detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_lot_id: Mapped[int] = mapped_column(ForeignKey("parking_lots.id"), nullable=False, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("parking_lot_cameras.id"), nullable=False, index=True)
    parking_space_id: Mapped[Optional[int]] = mapped_column(ForeignKey("parking_spaces.id"), nullable=True, index=True)
    space_code: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    previous_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    occupied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_iou: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bounding_box: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    polygon: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raw_detection: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    parking_lot: Mapped["ParkingLot"] = relationship(back_populates="detections")
    camera: Mapped["ParkingLotCamera"] = relationship(back_populates="detections")
    space: Mapped[Optional["ParkingSpace"]] = relationship(back_populates="detections")
