from __future__ import annotations

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.services.app_settings import (
    add_admin_id,
    get_admin_ids,
    get_admin_usernames,
    remove_admin_username,
)


def _parse_admin_ids(raw: str) -> set[int]:
    s = (raw or "").strip()
    if not s:
        return set()
    out: set[int] = set()
    for part in s.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except Exception:
            continue
    return out


def _parse_admin_usernames(raw: str) -> set[str]:
    s = (raw or "").strip()
    if not s:
        return set()
    out: set[str] = set()
    for part in s.split(","):
        u = (part or "").strip()
        if not u:
            continue
        if u.startswith("@"):
            u = u[1:]
        if u:
            out.add(u.lower())
    return out


def _norm_username(username: str | None) -> str:
    u = (username or "").strip()
    if u.startswith("@"):
        u = u[1:]
    return u.lower()


def is_admin(chat_id: int, telegram_user_id: int, username: str | None) -> bool:
    """
    Admin recognition order:
      1) ADMIN_CHAT_ID (if set): allow any admin command only from that chat
      2) DB admin_ids/admin_usernames (managed via bot)
      3) ADMIN_TELEGRAM_IDS (optional): allow if user_id in list
      4) ADMIN_USERNAME / ADMIN_USERNAMES (bootstrap/fallback): allow if username matches

    Note: Telegram doesn't allow resolving username -> user_id in general.
    We "learn" the numeric ID when the user messages the bot, then persist it in DB.
    """
    if settings.ADMIN_CHAT_ID is not None and int(chat_id) == int(settings.ADMIN_CHAT_ID):
        return True

    uid = int(telegram_user_id)
    uname = _norm_username(username)

    # DB-managed admins
    try:
        with db_session() as db:
            db_ids = get_admin_ids(db)
            if uid in db_ids:
                return True
            db_names = get_admin_usernames(db)
            if uname and uname in db_names:
                # Promote: once we see the user_id, store it and remove username from "pending".
                try:
                    add_admin_id(db, uid)
                    remove_admin_username(db, uname)
                except Exception:
                    pass
                return True
    except Exception:
        pass

    # Backward-compatible env admins
    if uid in _parse_admin_ids(settings.ADMIN_TELEGRAM_IDS):
        return True

    # Bootstrap admin by username (env)
    bootstrap = _norm_username(getattr(settings, "ADMIN_USERNAME", ""))
    if bootstrap and uname == bootstrap:
        # Persist learned numeric ID for future robustness
        try:
            with db_session() as db:
                add_admin_id(db, uid)
        except Exception:
            pass
        return True

    if uname and uname in _parse_admin_usernames(settings.ADMIN_USERNAMES):
        return True
    return False

