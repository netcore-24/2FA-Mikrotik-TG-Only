from __future__ import annotations

import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.services.users import bind_account, list_users
from mikrotik_2fa_bot.models import User
from mikrotik_2fa_bot.services.um_cache import (
    refresh_um_users_cache,
    count_um_users_cache,
    list_um_users_page,
)


CHOOSE_TG, CHOOSE_UM = range(2)
PAGE_SIZE = 12


def _tg_page_kb(users: list[User], page: int) -> InlineKeyboardMarkup:
    page = max(0, int(page))
    start = page * PAGE_SIZE
    end = min(len(users), start + PAGE_SIZE)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(start, end):
        u = users[i]
        label = f"{u.telegram_id} | {u.full_name or '-'} | {u.status.value}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"tg_pick:{u.telegram_id}")])
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"tg_page:{page-1}"))
    if end < len(users):
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"tg_page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("Отмена", callback_data="um_cancel")])
    return InlineKeyboardMarkup(rows)


def _um_page_kb(items, page: int, total: int) -> InlineKeyboardMarkup:
    page = max(0, int(page))
    total = max(0, int(total))
    start = page * PAGE_SIZE
    end = min(total, start + max(0, len(items)))
    kb_rows: list[list[InlineKeyboardButton]] = []
    for r in items:
        label = (getattr(r, "username", "") or "").strip() or "-"
        rid = int(getattr(r, "id", 0) or 0)
        kb_rows.append([InlineKeyboardButton(label[:60], callback_data=f"um_pick_id:{rid}")])
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"um_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"um_page:{page+1}"))
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("Отмена", callback_data="um_cancel")])
    return InlineKeyboardMarkup(kb_rows)


async def um_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text("Недостаточно прав.")
        return ConversationHandler.END
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        # show list of known users
        with db_session() as db:
            users = list_users(db, limit=500)
        if not users:
            await msg.reply_text("Нет зарегистрированных пользователей. Пусть пользователь напишет /start или создайте его через /create_user.")
            return ConversationHandler.END
        context.user_data["tg_users"] = users
        await msg.reply_text("Выберите Telegram пользователя:", reply_markup=_tg_page_kb(users, 0))
    return CHOOSE_TG


async def um_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.message.chat_id, q.from_user.id, getattr(q.from_user, "username", None)):
        await q.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    data = q.data or ""
    if data == "um_cancel":
        await q.edit_message_text("Отменено.")
        return ConversationHandler.END

    # Step 1: choose Telegram user
    tg_users: list[User] = context.user_data.get("tg_users") or []
    if data.startswith("tg_page:"):
        page = int(data.split("tg_page:", 1)[1])
        await q.edit_message_reply_markup(reply_markup=_tg_page_kb(tg_users, page))
        return CHOOSE_TG

    if data.startswith("tg_pick:"):
        tid = int(data.split("tg_pick:", 1)[1])
        context.user_data["um_link_tid"] = tid

        await q.edit_message_text("⏳ Загружаю список User Manager пользователей…")
        try:
            def _job():
                with db_session() as db:
                    refresh_um_users_cache(db)
                    total = count_um_users_cache(db)
                    first = list_um_users_page(db, 0, PAGE_SIZE)
                    return total, first

            total, first_rows = await asyncio.to_thread(_job)
        except Exception as e:
            await q.edit_message_text(f"Не удалось получить список User Manager users: {e}")
            return ConversationHandler.END
        if not total:
            await q.edit_message_text("User Manager users не найдены на роутере.")
            return ConversationHandler.END
        await q.edit_message_text(
            f"Выберите User Manager пользователя для привязки (всего: {total}):",
            reply_markup=_um_page_kb(first_rows, 0, total),
        )
        return CHOOSE_UM

    if data.startswith("um_page:"):
        page = int(data.split("um_page:", 1)[1])
        with db_session() as db:
            total = count_um_users_cache(db)
            page_rows = list_um_users_page(db, page, PAGE_SIZE)
        await q.edit_message_reply_markup(reply_markup=_um_page_kb(page_rows, page, total))
        return CHOOSE_UM

    if data.startswith("um_pick_id:"):
        rid = int(data.split("um_pick_id:", 1)[1])
        tid = int(context.user_data.get("um_link_tid") or 0)
        if not tid:
            await q.edit_message_text("Сессия устарела. Запустите снова.")
            return ConversationHandler.END
        try:
            with db_session() as db:
                from mikrotik_2fa_bot.models import UmUserCache

                row = db.query(UmUserCache).filter(UmUserCache.id == rid).first()
                if not row:
                    await q.edit_message_text("UM пользователь не найден (кэш устарел). Запустите /link_um заново.")
                    return ConversationHandler.END
                uname = row.username
                bind_account(db, tid, uname)
            await q.edit_message_text(f"✅ Привязано: telegram_id={tid} → UM user={uname}")
        except Exception as e:
            await q.edit_message_text(f"❌ Ошибка привязки: {e}")
        return ConversationHandler.END

    await q.edit_message_text("Неизвестное действие.")
    return ConversationHandler.END

