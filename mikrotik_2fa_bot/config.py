from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import field_validator

import re


class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    ADMIN_CHAT_ID: int | None = None
    # IMPORTANT: keep these as strings, because pydantic-settings treats List[...] as JSON-in-env
    # and will crash on empty values like ADMIN_TELEGRAM_IDS=.
    ADMIN_TELEGRAM_IDS: str = ""   # "123,456"
    ADMIN_USERNAMES: str = ""     # "admin1,admin2" (without @)

    # Database
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # RouterOS API
    MIKROTIK_HOST: str = ""
    MIKROTIK_PORT: int = 8728
    MIKROTIK_USE_SSL: bool = False
    MIKROTIK_USERNAME: str = ""
    MIKROTIK_PASSWORD: str = ""
    MIKROTIK_TIMEOUT_SECONDS: int = 5

    # Behavior
    POLL_INTERVAL_SECONDS: int = 5
    POLL_MIKROTIK_TIMEOUT_SECONDS: int = 4
    REQUIRE_CONFIRMATION: bool = True
    CONFIRMATION_TIMEOUT_SECONDS: int = 300
    # If >0: resend the 2FA confirmation message every N seconds while the client stays connected.
    # Resends are limited by CONFIRMATION_MAX_RESENDS.
    CONFIRMATION_RESEND_SECONDS: int = 60
    CONFIRMATION_MAX_RESENDS: int = 3
    # When router no longer reports the session as active, wait this long before disconnecting
    # (handles short drops / polling jitter).
    DISCONNECT_GRACE_SECONDS: int = 30
    SESSION_DURATION_HOURS: int = 24
    SESSION_SOURCE: str = "user_manager"  # strictly user_manager

    FIREWALL_COMMENT_PREFIX: str = "2FA"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @field_validator("TELEGRAM_BOT_TOKEN", mode="before")
    @classmethod
    def _sanitize_bot_token(cls, v):
        s = "" if v is None else str(v)
        # remove ASCII control chars (including ESC from arrow keys)
        s = "".join(ch for ch in s if (ord(ch) >= 32 and ord(ch) != 127))
        s = s.strip()
        # If user pasted token with terminal escape sequences (e.g. arrow keys),
        # try to extract the first valid-looking token substring.
        m = re.search(r"(\d{5,20}:[A-Za-z0-9_-]{20,})", s)
        if m:
            return m.group(1)
        # Fallback: keep only characters that can appear in a BotFather token
        s = re.sub(r"[^0-9A-Za-z:_-]+", "", s)
        return s

    @field_validator("ADMIN_CHAT_ID", mode="before")
    @classmethod
    def _parse_admin_chat_id(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return int(s)


settings = Settings()

