from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
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
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("user_roles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped["UserRole"] = relationship(back_populates="accounts")
    sessions: Mapped[list["AccountSession"]] = relationship(back_populates="account")
    created_parking_lots: Mapped[list["ParkingLot"]] = relationship(back_populates="created_by")
    created_parking_cameras: Mapped[list["ParkingLotCamera"]] = relationship(back_populates="created_by")


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped["Account"] = relationship(back_populates="sessions")


class ParkingSpace(Base):
    __tablename__ = "parking_spaces"
    __table_args__ = (UniqueConstraint("code", name="uq_parking_spaces_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    zone: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[str] = mapped_column(String(50), default="Ground", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ParkingLot(Base):
    __tablename__ = "parking_lots"
    __table_args__ = (UniqueConstraint("name", name="uq_parking_lots_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    total_spots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by: Mapped[Optional["Account"]] = relationship(back_populates="created_parking_lots")
    cameras: Mapped[list["ParkingLotCamera"]] = relationship(
        back_populates="parking_lot",
        cascade="all, delete-orphan",
    )


class ParkingLotCamera(Base):
    __tablename__ = "parking_lot_cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_lot_id: Mapped[int] = mapped_column(ForeignKey("parking_lots.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    camera_type: Mapped[str] = mapped_column(String(30), nullable=False)
    stream_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parking_lot: Mapped["ParkingLot"] = relationship(back_populates="cameras")
    created_by: Mapped[Optional["Account"]] = relationship(back_populates="created_parking_cameras")
