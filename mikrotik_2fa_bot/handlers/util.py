from __future__ import annotations

from mikrotik_2fa_bot.config import settings


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


def is_admin(chat_id: int, telegram_user_id: int, username: str | None) -> bool:
    """
    Admin recognition order:
      1) ADMIN_CHAT_ID (if set): allow any admin command only from that chat
      2) ADMIN_TELEGRAM_IDS (recommended): allow if user_id in list
      3) ADMIN_USERNAMES (fallback): allow if username matches (without @, case-insensitive)
    """
    if settings.ADMIN_CHAT_ID is not None and int(chat_id) == int(settings.ADMIN_CHAT_ID):
        return True
    if int(telegram_user_id) in _parse_admin_ids(settings.ADMIN_TELEGRAM_IDS):
        return True
    u = (username or "").strip()
    if u.startswith("@"):
        u = u[1:]
    if u and u.lower() in _parse_admin_usernames(settings.ADMIN_USERNAMES):
        return True
    return False

