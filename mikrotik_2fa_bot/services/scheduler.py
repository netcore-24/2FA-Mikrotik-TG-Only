from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Optional

from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.models import SessionStatus
from mikrotik_2fa_bot.services import mikrotik_api
from mikrotik_2fa_bot.services.vpn_sessions import (
    list_sessions_to_poll,
    mark_connected,
    mark_confirm_requested,
    confirm_session,
    disconnect_session,
    expire_session,
)


logger = logging.getLogger(__name__)


def _active_map(sessions: list[mikrotik_api.ActiveSession]) -> Dict[str, mikrotik_api.ActiveSession]:
    m: Dict[str, mikrotik_api.ActiveSession] = {}
    for s in sessions:
        if s.username not in m:
            m[s.username] = s
    return m


def _is_expired(expires_at) -> bool:
    if not expires_at:
        return False
    return expires_at < datetime.utcnow()


async def poll_once(bot) -> None:
    """
    Poll RouterOS for active sessions and update DB sessions.
    This runs inside the Telegram bot process.
    """
    try:
        active = mikrotik_api.list_active_sessions(settings.SESSION_SOURCE)
    except Exception as e:  # noqa: BLE001
        logger.error("MikroTik poll failed: %s", e)
        return

    active_by_user = _active_map(active)

    with db_session() as db:
        sessions = list_sessions_to_poll(db)
        for s in sessions:
            # Expiry check
            if _is_expired(s.expires_at):
                expire_session(db, s)
                try:
                    await bot.send_message(chat_id=s.user.telegram_id, text="⌛️ VPN-сессия истекла. Доступ отключен.")
                except Exception:
                    pass
                continue

            a = active_by_user.get(s.mikrotik_username)
            if a:
                # seen as connected
                mark_connected(db, s, mikrotik_session_id=a.session_id)

                if s.status == SessionStatus.CONNECTED:
                    # If confirmation is required, request it (once)
                    if bool(settings.REQUIRE_CONFIRMATION):
                        # Ask user
                        try:
                            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                            kb = InlineKeyboardMarkup(
                                [[
                                    InlineKeyboardButton("✅ Да", callback_data=f"confirm:{s.id}:yes"),
                                    InlineKeyboardButton("❌ Нет", callback_data=f"confirm:{s.id}:no"),
                                ]]
                            )
                            await bot.send_message(
                                chat_id=s.user.telegram_id,
                                text=(
                                    "❓ Обнаружено подключение к VPN.\n\n"
                                    f"MikroTik user: {s.mikrotik_username}\n"
                                    f"Session: {a.session_id or '-'}\n\n"
                                    "Это вы подключились?"
                                ),
                                reply_markup=kb,
                            )
                            mark_confirm_requested(db, s)
                        except Exception as e:  # noqa: BLE001
                            logger.error("Failed to send confirmation request: %s", e)
                    else:
                        # Auto-confirm
                        try:
                            _try_enable_firewall_for_user(db, s)
                        except Exception:
                            pass
                        confirm_session(db, s, firewall_rule_id=s.firewall_rule_id)
                        try:
                            await bot.send_message(chat_id=s.user.telegram_id, text="✅ Подключение подтверждено. Доступ открыт.")
                        except Exception:
                            pass
                elif s.status == SessionStatus.CONFIRM_REQUESTED:
                    # timeout?
                    if s.confirm_requested_at:
                        age = (datetime.utcnow() - s.confirm_requested_at).total_seconds()
                        if age > int(settings.CONFIRMATION_TIMEOUT_SECONDS):
                            disconnect_session(db, s)
                            try:
                                await bot.send_message(chat_id=s.user.telegram_id, text="❌ Подтверждение не получено вовремя. Доступ отключен.")
                            except Exception:
                                pass
            else:
                # not active on router
                if s.status in {SessionStatus.CONNECTED, SessionStatus.CONFIRM_REQUESTED, SessionStatus.ACTIVE}:
                    # grace via last_seen_at
                    grace = max(30, int(settings.POLL_INTERVAL_SECONDS) * 2)
                    last_seen = s.last_seen_at or s.connected_at
                    if last_seen and (datetime.utcnow() - last_seen).total_seconds() < grace:
                        continue
                    disconnect_session(db, s)
                    try:
                        await bot.send_message(chat_id=s.user.telegram_id, text="🔌 Подключение к VPN завершено. Доступ отключен.")
                    except Exception:
                        pass


def _try_enable_firewall_for_user(db, session) -> Optional[str]:
    """
    If user has a configured firewall comment, try enabling the first rule that matches it.
    Otherwise try a heuristic: FIREWALL_COMMENT_PREFIX + username.
    """
    user = session.user
    comment = (getattr(user, "firewall_rule_comment", None) or "").strip()
    if not comment:
        prefix = (settings.FIREWALL_COMMENT_PREFIX or "").strip()
        if prefix:
            comment = f"{prefix} {session.mikrotik_username}"
    if not comment:
        return None
    rule = mikrotik_api.find_firewall_rule_by_comment_substring(comment)
    if not rule:
        return None
    rid = rule.get(".id") or rule.get("id")
    if not rid:
        return None
    mikrotik_api.set_firewall_rule_enabled(str(rid), enabled=True)
    session.firewall_rule_id = str(rid)
    db.commit()
    return str(rid)

