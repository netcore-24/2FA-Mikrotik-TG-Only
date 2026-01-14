from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.models import SessionStatus, VpnSession
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


def _is_expired(expires_at) -> bool:
    if not expires_at:
        return False
    return expires_at < datetime.utcnow()


async def poll_once(bot) -> None:
    """
    Poll RouterOS for active sessions and update DB sessions.
    This runs inside the Telegram bot process.
    """
    # First: load sessions to poll (cheap) to know which usernames we care about.
    with db_session() as db:
        sessions = list_sessions_to_poll(db)
        session_ids = [s.id for s in sessions]
        usernames = {s.mikrotik_username for s in sessions if s.mikrotik_username}

    if not session_ids:
        return

    # IMPORTANT: MikroTik API calls are synchronous and may block for seconds.
    # Run them in a thread + enforce timeout so the Telegram event loop stays responsive.
    try:
        active_by_user = await asyncio.wait_for(
            asyncio.to_thread(mikrotik_api.list_active_sessions_map_for_users, usernames, settings.SESSION_SOURCE),
            timeout=float(settings.POLL_MIKROTIK_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        logger.error("MikroTik poll failed: timed out")
        return
    except Exception as e:  # noqa: BLE001
        logger.error("MikroTik poll failed: %s", e)
        return

    # Re-open DB session for updates (avoid holding DB connection during network calls)
    with db_session() as db:
        sessions = db.query(VpnSession).filter(VpnSession.id.in_(session_ids)).all()
        for s in sessions:
            now = datetime.utcnow()
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
                    per_user = getattr(s.user, "require_confirmation", None)
                    require_confirm = bool(settings.REQUIRE_CONFIRMATION) if per_user is None else bool(per_user)
                    if require_confirm:
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
                    # Optional resend of confirmation request while client stays connected
                    try:
                        resend_every = int(getattr(settings, "CONFIRMATION_RESEND_SECONDS", 0) or 0)
                        max_resends = int(getattr(settings, "CONFIRMATION_MAX_RESENDS", 0) or 0)
                        if resend_every > 0 and max_resends > 0:
                            last_sent = getattr(s, "confirm_last_sent_at", None) or s.confirm_requested_at
                            sent_count = int(getattr(s, "confirm_sent_count", 0) or 0)
                            if last_sent and sent_count < max_resends:
                                if (now - last_sent).total_seconds() >= resend_every:
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
                                            "⏳ Напоминание: подтвердите подключение к VPN.\n\n"
                                            f"MikroTik user: {s.mikrotik_username}\n"
                                            f"Session: {a.session_id or '-'}\n\n"
                                            "Это вы подключились?"
                                        ),
                                        reply_markup=kb,
                                    )
                                    s.confirm_last_sent_at = now
                                    s.confirm_sent_count = sent_count + 1
                                    db.commit()
                    except Exception as e:  # noqa: BLE001
                        logger.error("Failed to resend confirmation request: %s", e)

                    # Total timeout?
                    if s.confirm_requested_at:
                        age = (now - s.confirm_requested_at).total_seconds()
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
                    grace = int(getattr(settings, "DISCONNECT_GRACE_SECONDS", 0) or 0)
                    if grace <= 0:
                        grace = max(30, int(settings.POLL_INTERVAL_SECONDS) * 2)
                    last_seen = s.last_seen_at or s.connected_at
                    if last_seen and (now - last_seen).total_seconds() < grace:
                        continue
                    disconnect_session(db, s)
                    try:
                        await bot.send_message(chat_id=s.user.telegram_id, text="🔌 Подключение к VPN завершено. Доступ отключен.")
                    except Exception:
                        pass


def _try_enable_firewall_for_user(db, session) -> Optional[str]:
    """
    Prefer per-user firewall_rule_id if configured.
    Otherwise:
      - If user has a configured firewall comment, try enabling the first rule that matches it.
      - Else try heuristic: FIREWALL_COMMENT_PREFIX + username.
    """
    user = session.user
    rid_pref = (getattr(user, "firewall_rule_id", None) or "").strip()
    if rid_pref:
        mikrotik_api.set_firewall_rule_enabled(rid_pref, enabled=True)
        session.firewall_rule_id = rid_pref
        db.commit()
        return rid_pref

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

