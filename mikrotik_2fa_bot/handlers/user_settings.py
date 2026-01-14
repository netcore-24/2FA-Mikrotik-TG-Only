from __future__ import annotations

import asyncio
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.models import User
from mikrotik_2fa_bot.services.users import list_users, bind_account, set_user_firewall_rule_id, cycle_user_require_confirmation
from mikrotik_2fa_bot.services.um_cache import refresh_um_users_cache_in_new_session, count_um_users_cache, list_um_users_page
from mikrotik_2fa_bot.services.fw_cache import refresh_firewall_rules_cache, count_firewall_rules_cache, list_firewall_rules_page


US_CHOOSE_USER, US_ACTION, US_CHOOSE_UM, US_CHOOSE_FW = range(4)
PAGE_SIZE = 10


def _short(s: str, n: int = 54) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _users_kb(users: list[User], page: int) -> InlineKeyboardMarkup:
    page = max(0, int(page))
    start = page * PAGE_SIZE
    end = min(len(users), start + PAGE_SIZE)
    rows: list[list[InlineKeyboardButton]] = []
    for u in users[start:end]:
        label = f"{u.telegram_id} | {u.full_name or '-'} | {u.status.value}"
        rows.append([InlineKeyboardButton(_short(label), callback_data=f"us_user_pick:{u.telegram_id}")])
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"us_user_page:{page-1}"))
    if end < len(users):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"us_user_page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("Отмена", callback_data="us_cancel")])
    return InlineKeyboardMarkup(rows)


def _action_kb(user: User) -> InlineKeyboardMarkup:
    rc = getattr(user, "require_confirmation", None)
    if rc is None:
        rc_label = f"2FA: по умолчанию ({'ON' if settings.REQUIRE_CONFIRMATION else 'OFF'})"
    else:
        rc_label = f"2FA: {'ON' if rc else 'OFF'}"
    fw = getattr(user, "firewall_rule_id", None) or "-"
    rows = [
        [InlineKeyboardButton("🔗 Привязать UM user", callback_data="us_action:bind_um")],
        [InlineKeyboardButton("🧱 Выбрать firewall rule", callback_data="us_action:set_fw")],
        [InlineKeyboardButton(_short(f"🛡️ {rc_label} (переключить)"), callback_data="us_action:toggle_2fa")],
        [InlineKeyboardButton(_short(f"🧱 Текущий rule: {fw} (очистить)"), callback_data="us_action:clear_fw")],
        [InlineKeyboardButton("⬅️ Назад к пользователям", callback_data="us_back:users")],
        [InlineKeyboardButton("Отмена", callback_data="us_cancel")],
    ]
    return InlineKeyboardMarkup(rows)


def _cache_kb(items, total: int, prefix: str, page: int, back_cb: str) -> InlineKeyboardMarkup:
    page = max(0, int(page))
    start = page * PAGE_SIZE
    total = max(0, int(total))
    end = min(total, start + max(0, len(items)))
    rows: list[list[InlineKeyboardButton]] = []
    for r in items:
        label = _short(getattr(r, "label", None) or getattr(r, "username", None) or "-")
        rid = int(getattr(r, "id", 0) or 0)
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}_pick_id:{rid}")])
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}_page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_cb)])
    rows.append([InlineKeyboardButton("Отмена", callback_data="us_cancel")])
    return InlineKeyboardMarkup(rows)


async def user_settings_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        if msg:
            await msg.reply_text("Недостаточно прав.")
        return ConversationHandler.END

    with db_session() as db:
        users = list_users(db, limit=500)
    if not users:
        if msg:
            await msg.reply_text("Нет пользователей в базе. Пусть пользователь напишет /start или создайте через /create_user.")
        return ConversationHandler.END

    context.user_data["us_users"] = users
    if msg:
        await msg.reply_text("⚙️ Настройки пользователя: выберите пользователя", reply_markup=_users_kb(users, 0))
    return US_CHOOSE_USER


async def user_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    uid = q.from_user.id
    username = getattr(q.from_user, "username", None)
    if not is_admin(chat_id, uid, username):
        await q.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    data = q.data or ""
    if data == "us_cancel":
        await q.edit_message_text("Отменено.")
        return ConversationHandler.END

    if data.startswith("us_user_page:"):
        users: list[User] = context.user_data.get("us_users") or []
        page = int(data.split("us_user_page:", 1)[1])
        await q.edit_message_reply_markup(reply_markup=_users_kb(users, page))
        return US_CHOOSE_USER

    if data.startswith("us_user_pick:"):
        tid = int(data.split("us_user_pick:", 1)[1])
        context.user_data["us_tid"] = tid
        with db_session() as db:
            u = db.query(User).filter(User.telegram_id == tid).first()
        if not u:
            await q.edit_message_text("Пользователь не найден (устаревший список).")
            return ConversationHandler.END
        await q.edit_message_text(f"Пользователь: {u.full_name or '-'} (telegram_id={u.telegram_id})", reply_markup=_action_kb(u))
        return US_ACTION

    if data == "us_back:users":
        users: list[User] = context.user_data.get("us_users") or []
        await q.edit_message_text("⚙️ Настройки пользователя: выберите пользователя", reply_markup=_users_kb(users, 0))
        return US_CHOOSE_USER

    if data == "us_back:actions":
        tid = int(context.user_data.get("us_tid") or 0)
        with db_session() as db:
            u = db.query(User).filter(User.telegram_id == tid).first()
        if not u:
            await q.edit_message_text("Сессия устарела. Запустите снова.")
            return ConversationHandler.END
        await q.edit_message_text(f"Пользователь: {u.full_name or '-'} (telegram_id={u.telegram_id})", reply_markup=_action_kb(u))
        return US_ACTION

    if data.startswith("us_action:"):
        action = data.split("us_action:", 1)[1]
        tid = int(context.user_data.get("us_tid") or 0)
        if not tid:
            await q.edit_message_text("Сессия устарела. Запустите снова.")
            return ConversationHandler.END

        if action == "toggle_2fa":
            with db_session() as db:
                u = cycle_user_require_confirmation(db, tid)
            await q.edit_message_text(f"Пользователь: {u.full_name or '-'} (telegram_id={u.telegram_id})", reply_markup=_action_kb(u))
            return US_ACTION

        if action == "clear_fw":
            with db_session() as db:
                set_user_firewall_rule_id(db, tid, None)
                u = db.query(User).filter(User.telegram_id == tid).first()
            await q.edit_message_text(f"Пользователь: {u.full_name or '-'} (telegram_id={u.telegram_id})", reply_markup=_action_kb(u))
            return US_ACTION

        if action == "bind_um":
            await q.edit_message_text("⏳ Загружаю список User Manager users…")
            try:
                await asyncio.to_thread(refresh_um_users_cache_in_new_session)
            except Exception as e:
                await q.edit_message_text(f"❌ Не удалось получить список UM users: {e}")
                return ConversationHandler.END
            with db_session() as db:
                total = count_um_users_cache(db)
                first = list_um_users_page(db, 0, PAGE_SIZE)
            if not total:
                await q.edit_message_text("User Manager users не найдены на роутере.")
                return ConversationHandler.END
            await q.edit_message_text(
                f"Выберите UM пользователя (всего: {total}):",
                reply_markup=_cache_kb(first, total, "us_um", 0, "us_back:actions"),
            )
            return US_CHOOSE_UM

        if action == "set_fw":
            await q.edit_message_text("⏳ Загружаю firewall rules…")
            flt = (settings.FIREWALL_COMMENT_PREFIX or "").strip() or None
            try:
                await asyncio.to_thread(refresh_firewall_rules_cache, flt)
            except Exception as e:
                await q.edit_message_text(f"❌ Ошибка чтения firewall: {e}")
                return ConversationHandler.END
            with db_session() as db:
                total = count_firewall_rules_cache(db)
                first = list_firewall_rules_page(db, 0, PAGE_SIZE)
            if not total:
                await q.edit_message_text("Правила не найдены (попробуйте добавить comment или изменить FIREWALL_COMMENT_PREFIX).")
                return ConversationHandler.END
            await q.edit_message_text(
                f"Выберите firewall rule для пользователя (всего: {total}):",
                reply_markup=_cache_kb(first, total, "us_fw", 0, "us_back:actions"),
            )
            return US_CHOOSE_FW

        await q.edit_message_text("Неизвестное действие.")
        return ConversationHandler.END

    # UM selection
    if data.startswith("us_um_page:"):
        page = int(data.split("us_um_page:", 1)[1])
        with db_session() as db:
            total = count_um_users_cache(db)
            page_rows = list_um_users_page(db, page, PAGE_SIZE)
        await q.edit_message_reply_markup(reply_markup=_cache_kb(page_rows, total, "us_um", page, "us_back:actions"))
        return US_CHOOSE_UM
    if data.startswith("us_um_pick_id:"):
        pick_id = int(data.split("us_um_pick_id:", 1)[1])
        tid = int(context.user_data.get("us_tid") or 0)
        with db_session() as db:
            from mikrotik_2fa_bot.models import UmUserCache

            row = db.query(UmUserCache).filter(UmUserCache.id == pick_id).first()
            uname = (row.username if row else "").strip()
        if not uname:
            await q.edit_message_text("UM пользователь не найден (кэш устарел). Повторите попытку.")
            return ConversationHandler.END
        try:
            with db_session() as db:
                bind_account(db, tid, uname)
            await q.edit_message_text(f"✅ Привязано: telegram_id={tid} → UM user={uname}")
        except Exception as e:
            await q.edit_message_text(f"❌ Ошибка привязки: {e}")
        return ConversationHandler.END

    # Firewall selection
    if data.startswith("us_fw_page:"):
        page = int(data.split("us_fw_page:", 1)[1])
        with db_session() as db:
            total = count_firewall_rules_cache(db)
            page_rows = list_firewall_rules_page(db, page, PAGE_SIZE)
        await q.edit_message_reply_markup(reply_markup=_cache_kb(page_rows, total, "us_fw", page, "us_back:actions"))
        return US_CHOOSE_FW
    if data.startswith("us_fw_pick_id:"):
        pick_id = int(data.split("us_fw_pick_id:", 1)[1])
        tid = int(context.user_data.get("us_tid") or 0)
        with db_session() as db:
            from mikrotik_2fa_bot.models import FirewallRuleCache

            row = db.query(FirewallRuleCache).filter(FirewallRuleCache.id == pick_id).first()
            rid = (row.rule_id if row else "").strip()
            label = (row.label if row else "").strip()
        if not rid:
            await q.edit_message_text("Правило не найдено (кэш устарел). Повторите попытку.")
            return ConversationHandler.END
        try:
            with db_session() as db:
                set_user_firewall_rule_id(db, tid, rid)
            await q.edit_message_text(f"✅ Назначено firewall rule: telegram_id={tid} → rule_id={rid}\n{_short(label, 120)}")
        except Exception as e:
            await q.edit_message_text(f"❌ Ошибка сохранения: {e}")
        return ConversationHandler.END

    await q.edit_message_text("Неизвестное действие.")
    return ConversationHandler.END

