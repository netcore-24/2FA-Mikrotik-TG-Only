from __future__ import annotations

import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.handlers.menu import main_menu
from mikrotik_2fa_bot.models import UserStatus, VpnSession
from mikrotik_2fa_bot.services import mikrotik_api
from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.services.users import (
    list_pending_users,
    approve_user,
    reject_user,
    bind_account,
    unbind_account,
    set_user_firewall_comment,
    create_or_update_user,
)
from mikrotik_2fa_bot.services.vpn_sessions import list_active_sessions_all_users
from mikrotik_2fa_bot.services.app_settings import (
    add_admin_id,
    add_admin_username,
    get_admin_ids,
    get_admin_usernames,
    remove_admin_id,
    remove_admin_username,
)


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    with db_session() as db:
        items = list_pending_users(db)
    if not items:
        await update.message.reply_text("Нет заявок.")
        return
    await update.message.reply_text(f"Заявок: {len(items)}")
    for u in items[:30]:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Принять", callback_data=f"admin_approve:{u.telegram_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject:{u.telegram_id}"),
                ]
            ]
        )
        await update.message.reply_text(
            f"📝 {u.full_name}\ntelegram_id: {u.telegram_id}",
            reply_markup=kb,
        )


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /approve <telegram_id>")
        return
    tid = int(context.args[0])
    with db_session() as db:
        approve_user(db, tid)
    await update.message.reply_text(f"✅ Пользователь {tid} одобрен.")


async def reject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /reject <telegram_id> <reason>")
        return
    tid = int(context.args[0])
    reason = " ".join(context.args[1:])
    with db_session() as db:
        reject_user(db, tid, reason)
    await update.message.reply_text(f"❌ Пользователь {tid} отклонён.")


async def bind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /bind <telegram_id> <mikrotik_username>")
        return
    tid = int(context.args[0])
    uname = context.args[1].strip()
    with db_session() as db:
        bind_account(db, tid, uname)
    await update.message.reply_text(f"✅ Привязано: telegram_id={tid} → {uname}")


async def unbind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /unbind <telegram_id> <mikrotik_username>")
        return
    tid = int(context.args[0])
    uname = context.args[1].strip()
    with db_session() as db:
        unbind_account(db, tid, uname)
    await update.message.reply_text(f"✅ Отвязано: telegram_id={tid} → {uname}")


async def set_fw_comment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /set_fw_comment <telegram_id> <comment substring>")
        return
    tid = int(context.args[0])
    comment = " ".join(context.args[1:])
    with db_session() as db:
        set_user_firewall_comment(db, tid, comment)
    await update.message.reply_text("✅ Сохранено.")


async def create_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin: create/update a user and set them APPROVED immediately.
    Usage: /create_user <telegram_id> <full_name...>
    """
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /create_user <telegram_id> <full_name>")
        return
    tid = int(context.args[0])
    full_name = " ".join(context.args[1:])
    with db_session() as db:
        u = create_or_update_user(db, tid, full_name, status=UserStatus.APPROVED)
    await update.message.reply_text(f"✅ Пользователь создан/обновлён: {u.full_name} (telegram_id={u.telegram_id})")


async def test_router_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    from mikrotik_2fa_bot.config import settings
    await update.message.reply_text(
        "⏳ Тестирую подключение к роутеру...\n"
        f"Host: {settings.MIKROTIK_HOST}:{settings.MIKROTIK_PORT}\n"
        f"SSL: {settings.MIKROTIK_USE_SSL}\n"
        f"Timeout: {settings.MIKROTIK_TIMEOUT_SECONDS}s"
    )
    try:
        report = await asyncio.to_thread(mikrotik_api.test_connection_report)
        lines = [
            "✅ RouterOS API: OK",
            f"- identity: {report.identity or 'unknown'}",
            f"- tcp: {'OK' if report.tcp_ok else 'FAIL'}",
        ]
        if report.ip_service_api_enabled is not None:
            lines.append(f"- /ip/service api enabled: {report.ip_service_api_enabled}")
        if report.ip_service_api_ssl_enabled is not None:
            lines.append(f"- /ip/service api-ssl enabled: {report.ip_service_api_ssl_enabled}")
        if report.user_manager_ok is not None:
            lines.append(f"- user-manager доступ: {'OK' if report.user_manager_ok else 'FAIL'}")
        if report.firewall_ok is not None:
            lines.append(f"- firewall read: {'OK' if report.firewall_ok else 'FAIL'}")
        if report.notes:
            lines.append("")
            lines.extend([f"ℹ️ {n}" for n in report.notes[:5]])
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ RouterOS API ошибка: {e}")


async def admin_sessions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    with db_session() as db:
        sessions = list_active_sessions_all_users(db)
        if not sessions:
            await update.message.reply_text("Активных сессий нет.")
            return
        lines = []
        kb = []
        for s in sessions[:15]:
            lines.append(
                f"- {s.id[:8]}… | user={s.user.telegram_id if s.user else s.user_id} | mt={s.mikrotik_username} | {s.status.value}"
            )
            kb.append([InlineKeyboardButton(f"🔌 Отключить {s.mikrotik_username}", callback_data=f"admin_disconnect:{s.id}")])
    await update.message.reply_text(
        "Активные VPN-сессии:\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def restart_bot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin: restart bot process.
    We don't call systemctl from Telegram; instead we exit and systemd restarts us (Restart=always).
    """
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    await update.message.reply_text("♻️ Перезапускаю бота…")
    # Give Telegram a moment to deliver the message, then hard-exit.
    await asyncio.sleep(1)
    os._exit(0)  # noqa: S404


async def list_admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    with db_session() as db:
        ids = sorted(get_admin_ids(db))
        names = sorted(get_admin_usernames(db))
    boot = getattr(settings, "ADMIN_USERNAME", "") or ""
    lines = [
        "Администраторы (DB):",
        f"- ids: {', '.join(str(x) for x in ids) if ids else '-'}",
        f"- usernames (pending): {', '.join('@'+x for x in names) if names else '-'}",
    ]
    if boot:
        lines.append(f"\nBootstrap из env: @{boot.lstrip('@')}")
    await update.message.reply_text("\n".join(lines))


async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /add_admin <telegram_id|@username>")
        return
    arg = (context.args[0] or "").strip()
    if not arg:
        await update.message.reply_text("Использование: /add_admin <telegram_id|@username>")
        return
    with db_session() as db:
        if arg.lstrip("@").isdigit():
            tid = int(arg.lstrip("@"))
            add_admin_id(db, tid)
            await update.message.reply_text(f"✅ Админ добавлен: user_id={tid}")
            return
        # Username: will be promoted to ID when that user messages the bot
        add_admin_username(db, arg)
    await update.message.reply_text(
        "✅ Админ добавлен по username.\n"
        "Важно: Telegram не позволяет надёжно получить user_id по username.\n"
        "Когда этот пользователь напишет боту (/start), бот автоматически сохранит его user_id как админа."
    )


async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /remove_admin <telegram_id|@username>")
        return
    arg = (context.args[0] or "").strip()
    if not arg:
        await update.message.reply_text("Использование: /remove_admin <telegram_id|@username>")
        return
    with db_session() as db:
        if arg.lstrip("@").isdigit():
            tid = int(arg.lstrip("@"))
            remove_admin_id(db, tid)
            await update.message.reply_text(f"✅ Админ удалён: user_id={tid}")
            return
        remove_admin_username(db, arg)
    await update.message.reply_text(f"✅ Админ удалён: {arg}")

