from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.services.users import get_user_by_telegram_id


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db_session() as db:
        u = get_user_by_telegram_id(db, uid)
        status = u.status.value if u else "not_registered"
    await update.message.reply_text(
        "MikroTik 2FA VPN (Telegram-only)\n\n"
        "Команды:\n"
        "- /register — регистрация\n"
        "- /request_vpn — запросить доступ\n"
        "- /my_sessions — мои сессии\n"
        "- /disable_vpn — отключить доступ\n\n"
        f"Ваш статус: {status}"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_cmd(update, context)

