from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.handlers.util import is_admin_chat
from mikrotik_2fa_bot.services.users import (
    list_pending_users,
    approve_user,
    reject_user,
    bind_account,
    unbind_account,
    set_user_firewall_comment,
)


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_chat(update.effective_chat.id):
        await update.message.reply_text("Недостаточно прав.")
        return
    with db_session() as db:
        items = list_pending_users(db)
    if not items:
        await update.message.reply_text("Нет заявок.")
        return
    text = "Заявки:\n" + "\n".join([f"- {u.full_name} (telegram_id={u.telegram_id})" for u in items])
    await update.message.reply_text(text)


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_chat(update.effective_chat.id):
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
    if not is_admin_chat(update.effective_chat.id):
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
    if not is_admin_chat(update.effective_chat.id):
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
    if not is_admin_chat(update.effective_chat.id):
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
    if not is_admin_chat(update.effective_chat.id):
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

