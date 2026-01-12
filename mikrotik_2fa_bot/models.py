from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Enum,
    Text,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mikrotik_2fa_bot.db import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SessionStatus(str, enum.Enum):
    REQUESTED = "requested"  # account enabled, waiting for user to connect
    CONNECTED = "connected"  # connection detected
    CONFIRM_REQUESTED = "confirm_requested"  # 2FA message sent, waiting for user response
    ACTIVE = "active"  # confirmed and (optionally) firewall enabled
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int] = mapped_column(nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.PENDING, index=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Optional: used to find firewall rules by comment for this user
    firewall_rule_comment: Mapped[str | None] = mapped_column(String(255), nullable=True)

    accounts: Mapped[list["MikrotikAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["VpnSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class MikrotikAccount(Base):
    __tablename__ = "mikrotik_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    mikrotik_username: Mapped[str] = mapped_column(String(255), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="accounts")


Index("uq_user_mikrotik_username", MikrotikAccount.user_id, MikrotikAccount.mikrotik_username, unique=True)


class VpnSession(Base):
    __tablename__ = "vpn_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    mikrotik_username: Mapped[str] = mapped_column(String(255), index=True)

    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.REQUESTED, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirm_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    mikrotik_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    firewall_rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


Index("ix_vpn_sessions_user_status", VpnSession.user_id, VpnSession.status)

