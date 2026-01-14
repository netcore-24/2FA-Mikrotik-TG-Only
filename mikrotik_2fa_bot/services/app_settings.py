from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from mikrotik_2fa_bot.models import AppSetting


_KEY_PATH = Path("./data/settings.key")


def _ensure_key() -> bytes:
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_PATH.write_bytes(key)
    try:
        os.chmod(_KEY_PATH, 0o600)
    except Exception:
        pass
    return key


def _fernet() -> Fernet:
    return Fernet(_ensure_key())


def set_setting(db: Session, key: str, value: str, encrypt: bool = False) -> None:
    k = (key or "").strip()
    if not k:
        raise ValueError("empty_key")
    v = "" if value is None else str(value)
    is_enc = bool(encrypt)
    if is_enc:
        token = _fernet().encrypt(v.encode("utf-8"))
        v = token.decode("utf-8")
    row = db.query(AppSetting).filter(AppSetting.key == k).first()
    if not row:
        row = AppSetting(key=k, value=v, is_encrypted=is_enc)
        db.add(row)
    else:
        row.value = v
        row.is_encrypted = is_enc
    db.commit()


def get_setting(db: Session, key: str) -> Optional[str]:
    k = (key or "").strip()
    if not k:
        return None
    row = db.query(AppSetting).filter(AppSetting.key == k).first()
    if not row:
        return None
    if not row.is_encrypted:
        return row.value
    try:
        raw = _fernet().decrypt(row.value.encode("utf-8"))
        return raw.decode("utf-8")
    except Exception:
        return None


def get_setting_bool(db: Session, key: str) -> Optional[bool]:
    v = get_setting(db, key)
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return None


def get_setting_int(db: Session, key: str) -> Optional[int]:
    v = get_setting(db, key)
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except Exception:
        return None


def apply_router_overrides_to_runtime_settings(db: Session, settings_obj: Any) -> None:
    """
    Load app settings from DB and patch the runtime settings object.
    Keys (RouterOS API):
      - mikrotik_host, mikrotik_port, mikrotik_use_ssl, mikrotik_username, mikrotik_password, mikrotik_timeout_seconds
    Keys (behavior):
      - session_duration_hours
      - confirmation_timeout_seconds
      - confirmation_resend_seconds
      - confirmation_max_resends
      - disconnect_grace_seconds
    """
    host = get_setting(db, "mikrotik_host")
    port = get_setting_int(db, "mikrotik_port")
    use_ssl = get_setting_bool(db, "mikrotik_use_ssl")
    username = get_setting(db, "mikrotik_username")
    password = get_setting(db, "mikrotik_password")
    timeout = get_setting_int(db, "mikrotik_timeout_seconds")
    session_hours = get_setting_int(db, "session_duration_hours")
    confirm_timeout = get_setting_int(db, "confirmation_timeout_seconds")
    confirm_resend = get_setting_int(db, "confirmation_resend_seconds")
    confirm_max = get_setting_int(db, "confirmation_max_resends")
    disconnect_grace = get_setting_int(db, "disconnect_grace_seconds")

    if host:
        settings_obj.MIKROTIK_HOST = host
    if port:
        settings_obj.MIKROTIK_PORT = port
    if use_ssl is not None:
        settings_obj.MIKROTIK_USE_SSL = bool(use_ssl)
    if username:
        settings_obj.MIKROTIK_USERNAME = username
    if password:
        settings_obj.MIKROTIK_PASSWORD = password
    if timeout:
        settings_obj.MIKROTIK_TIMEOUT_SECONDS = timeout

    if session_hours:
        settings_obj.SESSION_DURATION_HOURS = session_hours
    if confirm_timeout:
        settings_obj.CONFIRMATION_TIMEOUT_SECONDS = confirm_timeout
    if confirm_resend is not None:
        # allow 0 to disable
        settings_obj.CONFIRMATION_RESEND_SECONDS = int(confirm_resend)
    if confirm_max is not None:
        settings_obj.CONFIRMATION_MAX_RESENDS = int(confirm_max)
    if disconnect_grace is not None:
        settings_obj.DISCONNECT_GRACE_SECONDS = int(disconnect_grace)

