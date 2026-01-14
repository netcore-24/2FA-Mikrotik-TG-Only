from __future__ import annotations

import asyncio
from telegram import Update
from telegram.ext import ContextTypes

from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.services import mikrotik_api
from mikrotik_2fa_bot.config import settings


async def firewall_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return

    # default filter: FIREWALL_COMMENT_PREFIX if set
    flt = (context.args[0].strip() if context.args else "") if context.args else ""
    if not flt:
        flt = settings.FIREWALL_COMMENT_PREFIX or ""

    await update.message.reply_text(f"⏳ Загружаю firewall rules (filter comment contains: '{flt}' )...")
    try:
        # Stream + limit to reduce memory on large configs
        rules = await asyncio.to_thread(mikrotik_api.list_firewall_filter_rules, flt if flt else None, 30)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка чтения firewall: {e}")
        return

    if not rules:
        await update.message.reply_text("Правила не найдены.")
        return

    lines = []
    for r in rules[:30]:
        rid = r.get(".id") or r.get("id") or "?"
        chain = r.get("chain") or "-"
        action = r.get("action") or "-"
        disabled = r.get("disabled")
        comment = (r.get("comment") or "").strip()
        lines.append(f"- {rid} | {chain} | {action} | disabled={disabled} | {comment}")
    await update.message.reply_text("Firewall rules:\n" + "\n".join(lines))

