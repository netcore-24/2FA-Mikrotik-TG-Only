from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from mikrotik_2fa_bot.models import User, UserStatus, MikrotikAccount


def get_user_by_telegram_id(db: Session, telegram_id: int) -> User | None:
    return db.query(User).filter(User.telegram_id == int(telegram_id)).first()


def upsert_pending_user(db: Session, telegram_id: int, full_name: str) -> User:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        user = User(telegram_id=int(telegram_id))
        db.add(user)
    user.full_name = (full_name or "").strip()
    user.status = UserStatus.PENDING
    user.rejected_reason = None
    user.approved_at = None
    db.commit()
    db.refresh(user)
    return user


def list_pending_users(db: Session) -> list[User]:
    return db.query(User).filter(User.status == UserStatus.PENDING).order_by(User.created_at.asc()).all()


def list_users(db: Session, limit: int = 200) -> list[User]:
    """
    List known users (users who registered or were created by admin).
    """
    return db.query(User).order_by(User.created_at.desc()).limit(int(limit)).all()


def approve_user(db: Session, telegram_id: int) -> User:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError("user_not_found")
    user.status = UserStatus.APPROVED
    user.rejected_reason = None
    user.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def reject_user(db: Session, telegram_id: int, reason: str) -> User:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError("user_not_found")
    user.status = UserStatus.REJECTED
    user.rejected_reason = (reason or "").strip() or "Rejected by admin"
    db.commit()
    db.refresh(user)
    return user


def create_or_update_user(
    db: Session,
    telegram_id: int,
    full_name: str,
    status: UserStatus = UserStatus.APPROVED,
) -> User:
    """
    Admin helper: create a user without waiting for /register, or update existing.
    Note: user still needs to start the bot once to receive messages from it.
    """
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        user = User(telegram_id=int(telegram_id))
        db.add(user)
    user.full_name = (full_name or "").strip()
    user.status = status
    if status == UserStatus.APPROVED:
        user.rejected_reason = None
        user.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def set_user_firewall_comment(db: Session, telegram_id: int, comment: str) -> User:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError("user_not_found")
    user.firewall_rule_comment = (comment or "").strip() or None
    db.commit()
    db.refresh(user)
    return user


def set_user_firewall_rule_id(db: Session, telegram_id: int, rule_id: str | None) -> User:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError("user_not_found")
    rid = (rule_id or "").strip() or None
    user.firewall_rule_id = rid
    db.commit()
    db.refresh(user)
    return user


def cycle_user_require_confirmation(db: Session, telegram_id: int) -> User:
    """
    Cycle user.require_confirmation: None -> True -> False -> None
    """
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError("user_not_found")
    cur = getattr(user, "require_confirmation", None)
    if cur is None:
        user.require_confirmation = True
    elif cur is True:
        user.require_confirmation = False
    else:
        user.require_confirmation = None
    db.commit()
    db.refresh(user)
    return user


def list_user_accounts(db: Session, user_id: str) -> list[MikrotikAccount]:
    return (
        db.query(MikrotikAccount)
        .filter(MikrotikAccount.user_id == user_id, MikrotikAccount.is_active == True)  # noqa: E712
        .order_by(MikrotikAccount.created_at.asc())
        .all()
    )


def bind_account(db: Session, telegram_id: int, mikrotik_username: str) -> MikrotikAccount:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        # Allow admin to bind UM user before the Telegram user registers.
        # The user still must press /start once to allow bot to message them.
        user = User(telegram_id=int(telegram_id), full_name="", status=UserStatus.APPROVED)
        db.add(user)
        db.commit()
        db.refresh(user)
    uname = (mikrotik_username or "").strip()
    if not uname:
        raise ValueError("invalid_username")
    acct = MikrotikAccount(user_id=user.id, mikrotik_username=uname, is_active=True)
    db.add(acct)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # If exists, reactivate
        acct2 = (
            db.query(MikrotikAccount)
            .filter(MikrotikAccount.user_id == user.id, MikrotikAccount.mikrotik_username == uname)
            .first()
        )
        if not acct2:
            raise
        acct2.is_active = True
        db.commit()
        db.refresh(acct2)
        return acct2
    db.refresh(acct)
    return acct


def unbind_account(db: Session, telegram_id: int, mikrotik_username: str) -> None:
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError("user_not_found")
    uname = (mikrotik_username or "").strip()
    acct = (
        db.query(MikrotikAccount)
        .filter(MikrotikAccount.user_id == user.id, MikrotikAccount.mikrotik_username == uname)
        .first()
    )
    if not acct:
        raise ValueError("account_not_found")
    acct.is_active = False
    db.commit()

