from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_

from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.models import SessionStatus, User, UserStatus, VpnSession
from mikrotik_2fa_bot.services import mikrotik_api


ACTIVE_STATUSES = {
    SessionStatus.REQUESTED,
    SessionStatus.CONNECTED,
    SessionStatus.CONFIRM_REQUESTED,
    SessionStatus.ACTIVE,
}


def get_active_session_for_user(db: Session, user_id: str) -> VpnSession | None:
    return (
        db.query(VpnSession)
        .filter(and_(VpnSession.user_id == user_id, VpnSession.status.in_(list(ACTIVE_STATUSES))))
        .order_by(VpnSession.created_at.desc())
        .first()
    )


def list_user_active_sessions(db: Session, user_id: str) -> list[VpnSession]:
    return (
        db.query(VpnSession)
        .filter(and_(VpnSession.user_id == user_id, VpnSession.status.in_(list(ACTIVE_STATUSES))))
        .order_by(VpnSession.created_at.desc())
        .all()
    )


def list_sessions_to_poll(db: Session) -> list[VpnSession]:
    return (
        db.query(VpnSession)
        .filter(VpnSession.status.in_(list(ACTIVE_STATUSES)))
        .order_by(VpnSession.created_at.asc())
        .all()
    )


def create_vpn_request(db: Session, user: User, mikrotik_username: str) -> VpnSession:
    if user.status != UserStatus.APPROVED:
        raise ValueError("user_not_approved")

    existing = get_active_session_for_user(db, user.id)
    if existing:
        raise ValueError("session_already_active")

    # Enable user on MikroTik BEFORE creating DB record.
    mikrotik_api.set_vpn_user_disabled(mikrotik_username, disabled=False)

    now = datetime.utcnow()
    session = VpnSession(
        user_id=user.id,
        mikrotik_username=mikrotik_username,
        status=SessionStatus.REQUESTED,
        expires_at=now + timedelta(hours=int(settings.SESSION_DURATION_HOURS)),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def mark_connected(db: Session, session: VpnSession, mikrotik_session_id: str | None) -> VpnSession:
    now = datetime.utcnow()
    if session.status == SessionStatus.REQUESTED:
        session.status = SessionStatus.CONNECTED
        session.connected_at = now
    session.last_seen_at = now
    if mikrotik_session_id:
        session.mikrotik_session_id = mikrotik_session_id
    db.commit()
    db.refresh(session)
    return session


def mark_confirm_requested(db: Session, session: VpnSession) -> VpnSession:
    now = datetime.utcnow()
    session.status = SessionStatus.CONFIRM_REQUESTED
    session.confirm_requested_at = now
    db.commit()
    db.refresh(session)
    return session


def confirm_session(db: Session, session: VpnSession, firewall_rule_id: str | None = None) -> VpnSession:
    now = datetime.utcnow()
    session.status = SessionStatus.ACTIVE
    session.confirmed_at = now
    if firewall_rule_id:
        session.firewall_rule_id = firewall_rule_id
    db.commit()
    db.refresh(session)
    return session


def disconnect_session(db: Session, session: VpnSession) -> VpnSession:
    session.status = SessionStatus.DISCONNECTED
    db.commit()
    db.refresh(session)

    # Best-effort: revoke access and tear down connection.
    try:
        if session.firewall_rule_id:
            mikrotik_api.set_firewall_rule_enabled(session.firewall_rule_id, enabled=False)
    except Exception:
        pass
    try:
        mikrotik_api.disconnect_active_connections(session.mikrotik_username)
    except Exception:
        pass
    try:
        mikrotik_api.set_vpn_user_disabled(session.mikrotik_username, disabled=True)
    except Exception:
        pass

    return session


def expire_session(db: Session, session: VpnSession) -> VpnSession:
    session.status = SessionStatus.EXPIRED
    db.commit()
    db.refresh(session)
    try:
        if session.firewall_rule_id:
            mikrotik_api.set_firewall_rule_enabled(session.firewall_rule_id, enabled=False)
    except Exception:
        pass
    try:
        mikrotik_api.set_vpn_user_disabled(session.mikrotik_username, disabled=True)
    except Exception:
        pass
    return session

