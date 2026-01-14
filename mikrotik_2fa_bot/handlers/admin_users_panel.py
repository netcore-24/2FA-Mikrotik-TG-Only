from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from mikrotik_2fa_bot.handlers.util import is_admin


async def admin_users_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Minimal admin panel for user management.
    Note: Inline keyboard requires a message. We keep it short (no command lists).
    """
    if not is_admin(update.effective_chat.id, update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("Недостаточно прав.")
        return ConversationHandler.END
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Заявки", callback_data="admin_panel:pending")],
            [InlineKeyboardButton("⚙️ Настройки пользователя", callback_data="admin_panel:user_settings")],
            [InlineKeyboardButton("🔗 Привязать UM user", callback_data="admin_panel:link_um")],
            [InlineKeyboardButton("👥 Сессии", callback_data="admin_panel:sessions")],
            [InlineKeyboardButton("🧱 Firewall", callback_data="admin_panel:firewall")],
            [
                InlineKeyboardButton("🧪 Тест роутера", callback_data="admin_panel:test_router"),
                InlineKeyboardButton("⚙️ Настройки роутера", callback_data="admin_panel:router_settings"),
            ],
            [InlineKeyboardButton("♻️ Перезапуск бота", callback_data="admin_panel:restart")],
        ]
    )
    await update.message.reply_text("🛡️ Админ-панель", reply_markup=kb)
    return ConversationHandler.END

