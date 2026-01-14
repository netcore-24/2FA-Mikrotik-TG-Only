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
    Integer,
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

    # Per-user override for 2FA confirmation:
    # - None: use global settings.REQUIRE_CONFIRMATION
    # - True/False: override globally
    require_confirmation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Preferred firewall rule id to enable for this user (RouterOS .id)
    firewall_rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
    # Tracks the last time we sent the 2FA confirmation prompt (for resends).
    confirm_last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Number of confirmation prompts sent for this session (first send counts as 1).
    confirm_sent_count: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    mikrotik_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    firewall_rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


Index("ix_vpn_sessions_user_status", VpnSession.user_id, VpnSession.status)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class UmUserCache(Base):
    """
    Cache of User Manager usernames for /link_um paging.
    Avoids keeping huge lists in bot memory.
    """
    __tablename__ = "um_user_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class FirewallRuleCache(Base):
    """
    Cache of firewall rules for paging selection in admin UI.
    Stores a short label + rule_id (.id) for selection.
    """
    __tablename__ = "firewall_rule_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(512), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

