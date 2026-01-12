from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    ADMIN_CHAT_ID: int | None = None

    # Database
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # RouterOS API
    MIKROTIK_HOST: str = ""
    MIKROTIK_PORT: int = 8728
    MIKROTIK_USE_SSL: bool = False
    MIKROTIK_USERNAME: str = ""
    MIKROTIK_PASSWORD: str = ""

    # Behavior
    POLL_INTERVAL_SECONDS: int = 5
    REQUIRE_CONFIRMATION: bool = True
    CONFIRMATION_TIMEOUT_SECONDS: int = 300
    SESSION_DURATION_HOURS: int = 24
    SESSION_SOURCE: str = "user_manager"  # strictly user_manager

    FIREWALL_COMMENT_PREFIX: str = "2FA"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

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

