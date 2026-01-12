from __future__ import annotations

from mikrotik_2fa_bot.config import settings


def is_admin_chat(chat_id: int) -> bool:
    """
    Admin commands are allowed ONLY from ADMIN_CHAT_ID.
    This matches the requirement "админский чат".
    """
    if settings.ADMIN_CHAT_ID is None:
        return False
    return int(chat_id) == int(settings.ADMIN_CHAT_ID)

