from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.models import VpnSession
from mikrotik_2fa_bot.services.vpn_sessions import confirm_session, disconnect_session
from mikrotik_2fa_bot.services.users import get_user_by_telegram_id
from mikrotik_2fa_bot.handlers.user import _create_request_for_username


logger = logging.getLogger(__name__)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data or ""

    if data.startswith("request:"):
        username = data.split("request:", 1)[1]
        await _create_request_for_username(context.bot, q.message.chat_id, q.from_user.id, username)
        return

    if data.startswith("confirm:"):
        _, session_id, decision = data.split(":", 2)
        uid = q.from_user.id
        with db_session() as db:
            user = get_user_by_telegram_id(db, uid)
            if not user:
                await q.edit_message_text("Пользователь не найден.")
                return
            s = db.query(VpnSession).filter(VpnSession.id == session_id).first()
            if not s or s.user_id != user.id:
                await q.edit_message_text("Сессия не найдена или не принадлежит вам.")
                return
            if decision == "no":
                disconnect_session(db, s)
                await q.edit_message_text("❌ Отклонено. Доступ отключен.")
                return
            # yes
            try:
                from mikrotik_2fa_bot.services.scheduler import _try_enable_firewall_for_user

                _try_enable_firewall_for_user(db, s)
            except Exception:
                pass
            confirm_session(db, s, firewall_rule_id=s.firewall_rule_id)
        await q.edit_message_text("✅ Подтверждено. Доступ открыт.")
        return

    if data.startswith("disconnect:"):
        session_id = data.split("disconnect:", 1)[1]
        uid = q.from_user.id
        with db_session() as db:
            user = get_user_by_telegram_id(db, uid)
            if not user:
                await q.edit_message_text("Пользователь не найден.")
                return
            s = db.query(VpnSession).filter(VpnSession.id == session_id).first()
            if not s or s.user_id != user.id:
                await q.edit_message_text("Сессия не найдена или не принадлежит вам.")
                return
            disconnect_session(db, s)
        await q.edit_message_text("🔌 Отключено.")
        return

    await q.edit_message_text("Неизвестное действие.")

