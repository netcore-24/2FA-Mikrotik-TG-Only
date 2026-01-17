from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.handlers.menu import main_menu
from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.services.users import get_user_by_telegram_id


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    username = getattr(update.effective_user, "username", None)
    with db_session() as db:
        u = get_user_by_telegram_id(db, uid)
        status = u.status.value if u else "not_registered"
    admin = is_admin(chat_id, uid, username)
    await update.message.reply_text(
        "MikroTik 2FA VPN\n"
        f"Статус: {status}\n\n"
        "Выберите действие кнопками ниже.",
        reply_markup=main_menu(is_admin=admin, user_status=status),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    username = getattr(update.effective_user, "username", None)
    with db_session() as db:
        u = get_user_by_telegram_id(db, uid)
        status = u.status.value if u else "not_registered"
    admin = is_admin(chat_id, uid, username)

    if admin:
        text = (
            "ℹ️ Инструкция (админ)\n\n"
            "Основной сценарий:\n"
            "1) Пользователь делает /register и ждёт одобрения.\n"
            "2) Вы одобряете заявки и привязываете UM-учётки (User Manager).\n"
            "3) Пользователь запрашивает доступ: /request_vpn.\n"
            "4) При подключении бот запрашивает 2FA подтверждение.\n\n"
            "Где что делать:\n"
            "- 🛡️ Админ → Заявки: одобрение/отклонение\n"
            "- 🛡️ Админ → Настройки роутера: host/port/ssl/user/pass/timeout (в рантайме)\n"
            "- 🛡️ Админ → Тест роутера: быстрая диагностика доступа к RouterOS API\n"
            "- /whoami: ваши user_id/chat_id\n\n"
            "Полезные команды:\n"
            "- /pending, /approve, /reject\n"
            "- /bind, /unbind\n"
            "- /router_settings\n"
            "- /test_router\n"
        )
    else:
        text = (
            "ℹ️ Инструкция (пользователь)\n\n"
            "Полный цикл:\n"
            "1) Нажмите 📝 Регистрация или выполните /register.\n"
            "2) Дождитесь, пока админ одобрит заявку.\n"
            "3) Запросите доступ: /request_vpn.\n"
            "4) Подключитесь к VPN.\n"
            "5) Бот попросит подтвердить вход (2FA) — подтвердите.\n\n"
            "Когда доступ отключается автоматически:\n"
            "- если вы отклонили 2FA или не подтвердили за время таймаута\n"
            "- если истекло время сессии (SESSION_DURATION_HOURS)\n"
            "- если админ отключил доступ\n\n"
            "Полезное:\n"
            "- /my_sessions — посмотреть активные сессии\n"
            "- /disable_vpn — отключить доступ вручную\n"
        )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(is_admin=admin, user_status=status),
    )


async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    c = update.effective_chat
    username = f"@{u.username}" if getattr(u, "username", None) else "-"
    await update.message.reply_text(
        "Ваши идентификаторы:\n"
        f"- user_id: {u.id}\n"
        f"- username: {username}\n"
        f"- chat_id: {c.id}\n"
    )


async def unknown_command_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Неизвестная команда. Используйте /help")


async def fallback_text_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Minimal, but important for UX: users often write "привет" instead of /start.
    await update.message.reply_text("Нажмите кнопки меню или напишите /start")

