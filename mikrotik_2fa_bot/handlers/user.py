from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.models import UserStatus, VpnSession
from mikrotik_2fa_bot.services import mikrotik_api
from mikrotik_2fa_bot.services.users import get_user_by_telegram_id, list_user_accounts
from mikrotik_2fa_bot.services.vpn_sessions import (
    create_vpn_request,
    list_user_active_sessions,
    get_active_session_for_user,
    disconnect_session,
)


async def request_vpn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db_session() as db:
        user = get_user_by_telegram_id(db, uid)
        if not user:
            await update.message.reply_text("Вы не зарегистрированы. Используйте /register.")
            return
        if user.status != UserStatus.APPROVED:
            await update.message.reply_text("Ваша заявка ещё не одобрена администратором.")
            return
        existing = get_active_session_for_user(db, user.id)
        if existing:
            await update.message.reply_text(f"У вас уже есть активная сессия: {existing.status.value} ({existing.id})")
            return
        accounts = list_user_accounts(db, user.id)
        usernames = [a.mikrotik_username for a in accounts]

    if not usernames:
        await update.message.reply_text("Администратор ещё не привязал ваш MikroTik аккаунт.")
        return
    if len(usernames) == 1:
        await _create_request_for_username(context.bot, update.effective_chat.id, uid, usernames[0])
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(u, callback_data=f"request:{u}")] for u in usernames[:20]])
    await update.message.reply_text("Выберите MikroTik аккаунт для активации:", reply_markup=kb)


async def my_sessions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db_session() as db:
        user = get_user_by_telegram_id(db, uid)
        if not user:
            await update.message.reply_text("Вы не зарегистрированы.")
            return
        sessions = list_user_active_sessions(db, user.id)
    if not sessions:
        await update.message.reply_text("Активных сессий нет.")
        return
    lines = []
    kb_rows = []
    for s in sessions[:10]:
        lines.append(f"- {s.id} | {s.mikrotik_username} | {s.status.value}")
        kb_rows.append([InlineKeyboardButton(f"🔌 Disconnect {s.mikrotik_username}", callback_data=f"disconnect:{s.id}")])
    await update.message.reply_text("Ваши активные сессии:\n" + "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows))


async def disable_vpn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db_session() as db:
        user = get_user_by_telegram_id(db, uid)
        if not user:
            await update.message.reply_text("Вы не зарегистрированы.")
            return
        sessions = list_user_active_sessions(db, user.id)
        accounts = list_user_accounts(db, user.id)
        for s in sessions:
            disconnect_session(db, s)
        for a in accounts:
            try:
                mikrotik_api.set_vpn_user_disabled(a.mikrotik_username, disabled=True)
            except Exception:
                pass
    await update.message.reply_text("Готово. Доступ отключен.")


async def _create_request_for_username(bot, chat_id: int, telegram_user_id: int, username: str):
    with db_session() as db:
        user = get_user_by_telegram_id(db, telegram_user_id)
        if not user:
            await bot.send_message(chat_id=chat_id, text="Вы не зарегистрированы.")
            return
        try:
            s = create_vpn_request(db, user, username)
        except mikrotik_api.MikroTikAPIError as e:
            await bot.send_message(chat_id=chat_id, text=f"Не удалось активировать аккаунт на MikroTik: {e}")
            return
        except Exception as e:
            await bot.send_message(chat_id=chat_id, text=f"Ошибка: {e}")
            return
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ Аккаунт активирован: {username}\n"
            f"ID запроса: {s.id}\n\n"
            "Подключайтесь к VPN. Если включена 2FA — придёт подтверждение."
        ),
    )

