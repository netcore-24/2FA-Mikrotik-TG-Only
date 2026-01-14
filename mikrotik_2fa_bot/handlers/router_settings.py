from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.services.app_settings import set_setting, get_setting
from mikrotik_2fa_bot.services.app_settings import apply_router_overrides_to_runtime_settings
from mikrotik_2fa_bot.config import settings


CHOOSE_FIELD, ENTER_VALUE = range(2)

FIELDS = {
    "host": ("mikrotik_host", "Host/IP"),
    "port": ("mikrotik_port", "Port (8728/8729)"),
    "ssl": ("mikrotik_use_ssl", "Use SSL (true/false)"),
    "user": ("mikrotik_username", "Username"),
    "pass": ("mikrotik_password", "Password"),
    "timeout": ("mikrotik_timeout_seconds", "Timeout seconds"),
    # behavior
    "sess_hours": ("session_duration_hours", "Session duration (hours)"),
    "confirm_to": ("confirmation_timeout_seconds", "2FA confirmation timeout (seconds)"),
    "confirm_resend": ("confirmation_resend_seconds", "2FA resend interval (seconds, 0=off)"),
    "confirm_max": ("confirmation_max_resends", "2FA max prompts per session (0=off)"),
    "disc_grace": ("disconnect_grace_seconds", "Disconnect grace (seconds)"),
}


def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Host", callback_data="rs:host"), InlineKeyboardButton("Port", callback_data="rs:port")],
            [InlineKeyboardButton("SSL", callback_data="rs:ssl"), InlineKeyboardButton("Username", callback_data="rs:user")],
            [InlineKeyboardButton("Password", callback_data="rs:pass"), InlineKeyboardButton("Timeout", callback_data="rs:timeout")],
            [InlineKeyboardButton("Session hours", callback_data="rs:sess_hours"), InlineKeyboardButton("2FA timeout", callback_data="rs:confirm_to")],
            [InlineKeyboardButton("2FA resend", callback_data="rs:confirm_resend"), InlineKeyboardButton("2FA max", callback_data="rs:confirm_max")],
            [InlineKeyboardButton("Disconnect grace", callback_data="rs:disc_grace")],
            [InlineKeyboardButton("Показать текущие", callback_data="rs:show")],
            [InlineKeyboardButton("Закрыть", callback_data="rs:close")],
        ]
    )


async def router_settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return ConversationHandler.END
    await update.message.reply_text("Настройки роутера (RouterOS API): выберите что изменить:", reply_markup=_kb())
    return CHOOSE_FIELD


async def router_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.message.chat_id, q.from_user.id, getattr(q.from_user, "username", None)):
        await q.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    data = q.data or ""
    if data == "rs:close":
        await q.edit_message_text("Закрыто.")
        return ConversationHandler.END
    if data == "rs:show":
        with db_session() as db:
            # Show EFFECTIVE values (DB override if set, else current runtime/.env)
            host = get_setting(db, "mikrotik_host") or settings.MIKROTIK_HOST
            port = get_setting(db, "mikrotik_port") or str(settings.MIKROTIK_PORT)
            ssl = get_setting(db, "mikrotik_use_ssl") or str(settings.MIKROTIK_USE_SSL)
            user = get_setting(db, "mikrotik_username") or settings.MIKROTIK_USERNAME
            pw = get_setting(db, "mikrotik_password") or settings.MIKROTIK_PASSWORD
            timeout = get_setting(db, "mikrotik_timeout_seconds") or str(settings.MIKROTIK_TIMEOUT_SECONDS)
            sess_h = get_setting(db, "session_duration_hours") or str(settings.SESSION_DURATION_HOURS)
            c_to = get_setting(db, "confirmation_timeout_seconds") or str(settings.CONFIRMATION_TIMEOUT_SECONDS)
            c_resend = get_setting(db, "confirmation_resend_seconds") or str(getattr(settings, "CONFIRMATION_RESEND_SECONDS", 0))
            c_max = get_setting(db, "confirmation_max_resends") or str(getattr(settings, "CONFIRMATION_MAX_RESENDS", 0))
            d_grace = get_setting(db, "disconnect_grace_seconds") or str(getattr(settings, "DISCONNECT_GRACE_SECONDS", 0))
        await q.edit_message_text(
            "Текущие настройки:\n"
            f"- host: {host}\n"
            f"- port: {port}\n"
            f"- use_ssl: {ssl}\n"
            f"- username: {user}\n"
            f"- password: {'(set)' if pw else '(empty)'}\n"
            f"- timeout: {timeout}\n\n"
            "VPN/2FA:\n"
            f"- session_duration_hours: {sess_h}\n"
            f"- confirmation_timeout_seconds: {c_to}\n"
            f"- confirmation_resend_seconds: {c_resend}\n"
            f"- confirmation_max_resends: {c_max}\n"
            f"- disconnect_grace_seconds: {d_grace}\n\n"
            "Выберите что изменить:",
            reply_markup=_kb(),
        )
        return CHOOSE_FIELD

    if not data.startswith("rs:"):
        return CHOOSE_FIELD
    key = data.split("rs:", 1)[1]
    if key not in FIELDS:
        return CHOOSE_FIELD
    db_key, label = FIELDS[key]
    context.user_data["router_setting_key"] = db_key
    context.user_data["router_setting_label"] = label
    await q.edit_message_text(f"Введите новое значение для: {label}")
    return ENTER_VALUE


async def router_settings_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return ConversationHandler.END
    key = context.user_data.get("router_setting_key")
    label = context.user_data.get("router_setting_label")
    if not key:
        await update.message.reply_text("Ошибка состояния. Запустите /router_settings заново.")
        return ConversationHandler.END
    val = (update.message.text or "").strip()
    encrypt = key == "mikrotik_password"
    with db_session() as db:
        set_setting(db, key, val, encrypt=encrypt)
        # Apply immediately (no restart required)
        apply_router_overrides_to_runtime_settings(db, settings)
    await update.message.reply_text(f"✅ Сохранено: {label}")
    await update.message.reply_text("Настройки роутера: выберите что изменить:", reply_markup=_kb())
    return CHOOSE_FIELD

