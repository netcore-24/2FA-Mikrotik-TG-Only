from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import ssl
from typing import Any, Dict, Iterable, List, Optional

from librouteros import connect as ros_connect

from mikrotik_2fa_bot.config import settings


class MikroTikAPIError(RuntimeError):
    pass


def _normalize_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"true", "yes", "enabled", "enable", "1"}:
        return True
    if s in {"false", "no", "disabled", "disable", "0"}:
        return False
    return None


def _bool_str(value: bool) -> str:
    # RouterOS API often expects boolean as "true"/"false" strings
    return "true" if bool(value) else "false"


@dataclass(frozen=True)
class ActiveSession:
    username: str
    session_id: Optional[str]
    source: str  # "user_manager" | "ppp_active"


@contextmanager
def ros_api():
    if not settings.MIKROTIK_HOST or not settings.MIKROTIK_USERNAME or not settings.MIKROTIK_PASSWORD:
        raise MikroTikAPIError("RouterOS API credentials are not configured (MIKROTIK_HOST/USERNAME/PASSWORD)")

    kwargs = {
        "host": settings.MIKROTIK_HOST,
        "port": int(settings.MIKROTIK_PORT),
        "username": settings.MIKROTIK_USERNAME,
        "password": settings.MIKROTIK_PASSWORD,
    }
    if bool(settings.MIKROTIK_USE_SSL):
        # Most RouterOS API-SSL installs use self-signed certs; disable verification.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_wrapper"] = ctx.wrap_socket

    api = None
    try:
        api = ros_connect(**kwargs)
        yield api
    except Exception as e:  # noqa: BLE001
        raise MikroTikAPIError(str(e)) from e
    finally:
        try:
            if api is not None and hasattr(api, "close"):
                api.close()
        except Exception:
            pass


def _find_user_manager_user(api, username: str) -> Optional[Dict[str, Any]]:
    for path in ("user-manager/user", "tool/user-manager/user"):
        try:
            items = list(api.path(path))
        except Exception:
            continue
        for u in items:
            if (u.get("username") == username) or (u.get("name") == username):
                return u
    return None


def set_vpn_user_disabled(username: str, disabled: bool) -> None:
    """
    Enable/disable an EXISTING VPN user on MikroTik.
    STRICT MODE:
      - User Manager user only (no PPP fallback)
    """
    with ros_api() as api:
        um = _find_user_manager_user(api, username)
        if not um:
            raise MikroTikAPIError(f"User Manager user '{username}' not found")
        rid = um.get(".id") or um.get("id")
        if not rid:
            raise MikroTikAPIError("User Manager user record has no .id")
        for path in ("user-manager/user", "tool/user-manager/user"):
            try:
                api.path(path).update(**{".id": rid, "disabled": _bool_str(disabled)})
                return
            except Exception:
                continue
        raise MikroTikAPIError("Failed to update User Manager user (all paths failed)")


def list_active_sessions(source: str = "auto") -> List[ActiveSession]:
    """
    Return active sessions in RouterOS.

    source:
      - "user_manager": /user-manager/session (active=true)
      - "ppp_active": /ppp/active (always active by definition)
      - "auto": try UM, fall back to PPP
    """
    source = (source or "user_manager").strip().lower()
    # STRICT: user_manager only
    if source != "user_manager":
        source = "user_manager"

    with ros_api() as api:
        last_exc: Exception | None = None
        for p in ("user-manager/session", "tool/user-manager/session"):
            try:
                items = list(api.path(p)) or []
            except Exception as e:
                last_exc = e
                continue
            out: List[ActiveSession] = []
            for s in items:
                if _normalize_bool(s.get("active")) is not True:
                    continue
                u = s.get("user") or s.get("username") or s.get("name")
                if not u:
                    continue
                sid = s.get("acct-session-id") or s.get("acct_session_id") or s.get(".id") or s.get("id")
                out.append(
                    ActiveSession(
                        username=str(u),
                        session_id=str(sid) if sid else None,
                        source="user_manager",
                    )
                )
            return out
        raise MikroTikAPIError(f"User Manager sessions are not available via RouterOS API: {last_exc}")


def disconnect_active_connections(username: str) -> None:
    """
    Best-effort disconnect:
      - remove matching /ppp/active record(s)
      - remove matching UM session(s) if API supports it
    """
    if not username:
        return
    with ros_api() as api:
        # PPP active
        try:
            ppp = api.path("ppp/active")
            items = list(ppp) or []
            for s in items:
                u = s.get("name") or s.get("user") or s.get("username")
                if str(u) != username:
                    continue
                rid = s.get(".id") or s.get("id")
                if rid:
                    try:
                        ppp.remove(rid)
                    except Exception:
                        pass
        except Exception:
            pass

        # User Manager sessions
        for p in ("user-manager/session", "tool/user-manager/session"):
            try:
                um = api.path(p)
                items = list(um) or []
            except Exception:
                continue
            for s in items:
                u = s.get("user") or s.get("username") or s.get("name")
                if str(u) != username:
                    continue
                if _normalize_bool(s.get("active")) is not True:
                    continue
                rid = s.get(".id") or s.get("id")
                if rid:
                    try:
                        um.remove(rid)
                    except Exception:
                        pass
            break


def find_firewall_rule_by_comment_substring(comment_substring: str) -> Optional[Dict[str, Any]]:
    needle = (comment_substring or "").strip().lower()
    if not needle:
        return None
    with ros_api() as api:
        try:
            rules = list(api.path("ip/firewall/filter")) or []
        except Exception as e:  # noqa: BLE001
            raise MikroTikAPIError(f"Failed to read firewall rules: {e}") from e
        for r in rules:
            c = str(r.get("comment") or "").lower()
            if needle in c:
                return r
    return None


def set_firewall_rule_enabled(rule_id: str, enabled: bool) -> None:
    rid = (rule_id or "").strip()
    if not rid:
        return
    with ros_api() as api:
        try:
            api.path("ip/firewall/filter").update(**{".id": rid, "disabled": _bool_str(not enabled)})
        except Exception as e:  # noqa: BLE001
            raise MikroTikAPIError(f"Failed to update firewall rule {rid}: {e}") from e

