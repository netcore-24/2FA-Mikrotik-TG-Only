from __future__ import annotations

import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.models import VpnSession
from mikrotik_2fa_bot.services.vpn_sessions import confirm_session, disconnect_session
from mikrotik_2fa_bot.services.users import get_user_by_telegram_id
from mikrotik_2fa_bot.handlers.user import _create_request_for_username
from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.services.users import approve_user, reject_user
from mikrotik_2fa_bot.handlers.um_link import um_link_start


logger = logging.getLogger(__name__)

async def _with_db_retry(fn, attempts: int = 3, delay: float = 0.25):
    last_exc: Exception | None = None
    for i in range(int(attempts)):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            # Retry only for typical sqlite lock errors
            msg = str(e).lower()
            if "database is locked" in msg or "locked" in msg:
                await asyncio.sleep(delay * (i + 1))
                continue
            raise
    if last_exc:
        raise last_exc


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    data = q.data or ""

    # Router settings inline keyboard (works both inside and outside the ConversationHandler state)
    if data.startswith("rs:"):
        from mikrotik_2fa_bot.handlers.router_settings import router_settings_callback

        return await router_settings_callback(update, context)

    await q.answer()

    # Simple UI menu callbacks (compact ReplyKeyboard -> inline submenu)
    if data == "menu_vpn:request":
        from mikrotik_2fa_bot.handlers.user import request_vpn_cmd
        fake_update = Update(update.update_id, message=q.message)
        fake_update._effective_user = q.from_user  # noqa: SLF001
        fake_update._effective_chat = q.message.chat  # noqa: SLF001
        await q.edit_message_text("Ок.")
        return await request_vpn_cmd(fake_update, context)
    if data == "menu_vpn:sessions":
        from mikrotik_2fa_bot.handlers.user import my_sessions_cmd
        fake_update = Update(update.update_id, message=q.message)
        fake_update._effective_user = q.from_user  # noqa: SLF001
        fake_update._effective_chat = q.message.chat  # noqa: SLF001
        await q.edit_message_text("Ок.")
        return await my_sessions_cmd(fake_update, context)
    if data == "menu_vpn:disable":
        from mikrotik_2fa_bot.handlers.user import disable_vpn_cmd
        fake_update = Update(update.update_id, message=q.message)
        fake_update._effective_user = q.from_user  # noqa: SLF001
        fake_update._effective_chat = q.message.chat  # noqa: SLF001
        await q.edit_message_text("Ок.")
        return await disable_vpn_cmd(fake_update, context)
    if data == "menu:help":
        from mikrotik_2fa_bot.handlers.basic import help_cmd
        fake_update = Update(update.update_id, message=q.message)
        fake_update._effective_user = q.from_user  # noqa: SLF001
        fake_update._effective_chat = q.message.chat  # noqa: SLF001
        await q.edit_message_text("Ок.")
        return await help_cmd(fake_update, context)

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

    if data.startswith("admin_disconnect:"):
        session_id = data.split("admin_disconnect:", 1)[1]
        uid = q.from_user.id
        chat_id = q.message.chat_id
        username = getattr(q.from_user, "username", None)
        if not is_admin(chat_id, uid, username):
            await q.edit_message_text("Недостаточно прав.")
            return
        with db_session() as db:
            s = db.query(VpnSession).filter(VpnSession.id == session_id).first()
            if not s:
                await q.edit_message_text("Сессия не найдена.")
                return
            disconnect_session(db, s)
        await q.edit_message_text("🔌 Отключено администратором.")
        return

    if data.startswith("admin_panel:"):
        chat_id = q.message.chat_id
        uid = q.from_user.id
        username = getattr(q.from_user, "username", None)
        if not is_admin(chat_id, uid, username):
            await q.edit_message_text("Недостаточно прав.")
            return
        action = data.split("admin_panel:", 1)[1]
        if action == "pending":
            # Trigger same as /pending but from callback
            from mikrotik_2fa_bot.handlers.admin import pending_cmd
            # Reuse message context: send new messages
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок, показываю заявки ниже.")
            return await pending_cmd(fake_update, context)
        if action == "sessions":
            from mikrotik_2fa_bot.handlers.admin import admin_sessions_cmd
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок, показываю активные сессии ниже.")
            return await admin_sessions_cmd(fake_update, context)
        if action == "test_router":
            from mikrotik_2fa_bot.handlers.admin import test_router_cmd
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок, тестирую роутер ниже.")
            return await test_router_cmd(fake_update, context)
        if action == "whoami":
            from mikrotik_2fa_bot.handlers.basic import whoami_cmd
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок.")
            return await whoami_cmd(fake_update, context)
        if action == "help":
            from mikrotik_2fa_bot.handlers.basic import help_cmd
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок.")
            return await help_cmd(fake_update, context)
        if action == "firewall":
            from mikrotik_2fa_bot.handlers.firewall import firewall_list_cmd
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок, читаю firewall rules ниже.")
            return await firewall_list_cmd(fake_update, context)
        if action == "restart":
            from mikrotik_2fa_bot.handlers.admin import restart_bot_cmd
            fake_update = Update(update.update_id, message=q.message)
            fake_update._effective_user = q.from_user  # noqa: SLF001
            fake_update._effective_chat = q.message.chat  # noqa: SLF001
            await q.edit_message_text("Ок.")
            return await restart_bot_cmd(fake_update, context)
        if action == "create_user":
            await q.edit_message_text("Используйте команду: /create_user <telegram_id> <ФИО>")
            return
        if action == "bind":
            await q.edit_message_text("Используйте команду: /bind <telegram_id> <mikrotik_username>")
            return
        # Let other, more specific handlers (ConversationHandler entrypoints) deal with it.
        return

    if data.startswith("admin_approve:") or data.startswith("admin_reject:"):
        chat_id = q.message.chat_id
        uid = q.from_user.id
        username = getattr(q.from_user, "username", None)
        if not is_admin(chat_id, uid, username):
            await q.edit_message_text("Недостаточно прав.")
            return
        action, tid_s = data.split(":", 1)
        try:
            tid = int(tid_s)
        except Exception:
            await q.edit_message_text("Некорректный telegram_id.")
            return
        try:
            def _op():
                with db_session() as db:
                    if action == "admin_approve":
                        approve_user(db, tid)
                    else:
                        reject_user(db, tid, "Rejected by admin")
            await _with_db_retry(_op)
            if action == "admin_approve":
                await q.edit_message_text(f"✅ Принято (telegram_id={tid})")
            else:
                await q.edit_message_text(f"❌ Отклонено (telegram_id={tid})")
        except Exception as e:  # noqa: BLE001
            logger.error("admin approve/reject failed: %s", e, exc_info=True)
            await q.edit_message_text(f"❌ Ошибка: {e}")
        return

    # Unknown callback: do not edit messages (avoid breaking other flows)
    return

