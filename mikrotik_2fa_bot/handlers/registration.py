from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.models import UserStatus
from mikrotik_2fa_bot.services.users import get_user_by_telegram_id, upsert_pending_user


REGISTER_FULLNAME = 1


async def register_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db_session() as db:
        u = get_user_by_telegram_id(db, uid)
        if u and u.status == UserStatus.APPROVED:
            await update.message.reply_text("Вы уже одобрены администратором.")
            return ConversationHandler.END
    context.user_data["awaiting_full_name"] = True
    await update.message.reply_text("Введите ваше имя и фамилию одним сообщением:")
    return REGISTER_FULLNAME


async def register_fullname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Имя слишком короткое. Попробуйте ещё раз:")
        return REGISTER_FULLNAME
    with db_session() as db:
        upsert_pending_user(db, uid, name)
    context.user_data.pop("awaiting_full_name", None)
    await update.message.reply_text("✅ Заявка отправлена. Ожидайте подтверждения администратора.")
    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_full_name", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

