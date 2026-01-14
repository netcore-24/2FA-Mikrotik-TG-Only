from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import inspect
import ssl
import socket
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

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


@dataclass(frozen=True, slots=True)
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
    # Best-effort: pass timeout if supported by this librouteros version
    try:
        sig = inspect.signature(ros_connect)
        if "timeout" in sig.parameters:
            kwargs["timeout"] = int(settings.MIKROTIK_TIMEOUT_SECONDS)
    except Exception:
        pass
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


def _iter_user_manager_users(api) -> Iterator[Dict[str, Any]]:
    """
    Yield UM user dicts without materializing the whole list.
    """
    last_exc: Exception | None = None
    for path in ("user-manager/user", "tool/user-manager/user"):
        try:
            for u in api.path(path):
                if isinstance(u, dict):
                    yield u
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            continue
    raise MikroTikAPIError(f"User Manager users are not available via RouterOS API: {last_exc}")


def iter_user_manager_usernames() -> Iterator[str]:
    """
    Yield User Manager usernames (normalized) without keeping all in memory.
    """
    with ros_api() as api:
        for u in _iter_user_manager_users(api):
            uname = u.get("username") or u.get("name")
            if uname:
                yield str(uname)


def _find_user_manager_user(api, username: str) -> Optional[Dict[str, Any]]:
    for u in _iter_user_manager_users(api):
        if (u.get("username") == username) or (u.get("name") == username):
            return u
    return None


def list_user_manager_users() -> List[Dict[str, Any]]:
    """
    List existing User Manager users via RouterOS API.
    STRICT MODE: User Manager must be available.
    """
    with ros_api() as api:
        # Normalize: prefer "username", fallback to "name"
        out: List[Dict[str, Any]] = []
        for u in _iter_user_manager_users(api):
            if not u.get("username") and u.get("name"):
                u["username"] = u.get("name")
            out.append(u)
        return out


def list_firewall_filter_rules(comment_substring: str | None = None, limit: int | None = None) -> List[Dict[str, Any]]:
    """
    List /ip/firewall/filter rules.
    If comment_substring is provided, returns only rules whose comment contains it (case-insensitive).
    If limit is provided, returns at most N matching rules (streaming, avoids keeping all rules in memory).
    """
    needle = (comment_substring or "").strip().lower()
    lim = None if limit is None else max(0, int(limit))
    with ros_api() as api:
        out: List[Dict[str, Any]] = []
        try:
            it = api.path("ip/firewall/filter")
        except Exception as e:  # noqa: BLE001
            raise MikroTikAPIError(f"Failed to read firewall rules: {e}") from e
        for r in it:
            if not isinstance(r, dict):
                continue
            if needle:
                c = str(r.get("comment") or "").lower()
                if needle not in c:
                    continue
            out.append(r)
            if lim is not None and lim > 0 and len(out) >= lim:
                break
        return out


def iter_firewall_filter_rules(comment_substring: str | None = None) -> Iterator[Dict[str, Any]]:
    """
    Yield /ip/firewall/filter rules (optionally filtered by comment substring).
    Streaming helper to avoid materializing large rule sets in memory.
    """
    needle = (comment_substring or "").strip().lower()
    with ros_api() as api:
        try:
            it = api.path("ip/firewall/filter")
        except Exception as e:  # noqa: BLE001
            raise MikroTikAPIError(f"Failed to read firewall rules: {e}") from e
        for r in it:
            if not isinstance(r, dict):
                continue
            if needle:
                c = str(r.get("comment") or "").lower()
                if needle not in c:
                    continue
            yield r

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
                items = api.path(p)
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


def list_active_sessions_map_for_users(usernames: Set[str], source: str = "auto") -> Dict[str, ActiveSession]:
    """
    Return only active sessions for the provided usernames.
    Streaming + early-stop to reduce peak memory on routers with lots of sessions.
    """
    need: Set[str] = {str(u) for u in (usernames or set()) if str(u)}
    if not need:
        return {}
    source = (source or "user_manager").strip().lower()
    if source != "user_manager":
        source = "user_manager"
    with ros_api() as api:
        last_exc: Exception | None = None
        for p in ("user-manager/session", "tool/user-manager/session"):
            try:
                items = api.path(p)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                continue
            out: Dict[str, ActiveSession] = {}
            remaining = set(need)
            for s in items:
                if _normalize_bool(s.get("active")) is not True:
                    continue
                u = s.get("user") or s.get("username") or s.get("name")
                if not u:
                    continue
                uname = str(u)
                if uname not in remaining:
                    continue
                sid = s.get("acct-session-id") or s.get("acct_session_id") or s.get(".id") or s.get("id")
                out[uname] = ActiveSession(username=uname, session_id=str(sid) if sid else None, source="user_manager")
                remaining.remove(uname)
                if not remaining:
                    break
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
            for s in ppp:
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
            except Exception:
                continue
            for s in um:
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
            rules = api.path("ip/firewall/filter")
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


def test_connection() -> str:
    """
    Simple connectivity test via RouterOS API.
    Returns router identity name (or raw response) on success.
    """
    # First: TCP probe to provide actionable diagnostics.
    host = settings.MIKROTIK_HOST
    port = int(settings.MIKROTIK_PORT)
    s = socket.socket()
    s.settimeout(float(settings.MIKROTIK_TIMEOUT_SECONDS))
    try:
        s.connect((host, port))
    except Exception as e:  # noqa: BLE001
        raise MikroTikAPIError(
            f"TCP connect failed to {host}:{port}: {e}. "
            "Проверьте что на MikroTik включен API сервис (/ip service enable api), "
            "порт (8728 или 8729 для api-ssl), и что firewall разрешает доступ с IP сервера."
        ) from e
    finally:
        try:
            s.close()
        except Exception:
            pass

    with ros_api() as api:
        try:
            items = list(api.path("system/identity"))
        except Exception as e:  # noqa: BLE001
            raise MikroTikAPIError(f"Failed to query /system/identity: {e}") from e
        if not items:
            return "OK (empty identity response)"
        name = items[0].get("name")
        return str(name or "OK")

