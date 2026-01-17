from __future__ import annotations

from telegram import ReplyKeyboardMarkup, KeyboardButton

from mikrotik_2fa_bot.models import UserStatus


BTN_START = "🏠 Меню"

BTN_VPN_MENU = "🔑 VPN"
BTN_ADMIN_MENU = "🛡️ Админ"

BTN_REGISTER = "📝 Регистрация"
BTN_REQUEST_VPN = "🔑 Запросить VPN"
BTN_MY_SESSIONS = "📡 Мои сессии"
BTN_DISABLE_VPN = "⛔ Отключить VPN"

BTN_ADMIN_PENDING = "🛡️ Админ: заявки"
BTN_ADMIN_USERS = "🛡️ Админ: пользователи"
BTN_ADMIN_SESSIONS = "🛡️ Админ: сессии"
BTN_ADMIN_RESTART_BOT = "🛡️ Админ: перезапуск бота"
BTN_ADMIN_FIREWALL = "🛡️ Админ: firewall"


def main_menu(is_admin: bool, user_status: str | None = None) -> ReplyKeyboardMarkup:
    """
    Persistent ReplyKeyboard menu.
    """
    # If user is registered (approved) and NOT admin, show only VPN menu.
    status = (user_status or "").strip().lower()
    if (not is_admin) and status == UserStatus.APPROVED.value:
        rows: list[list[KeyboardButton]] = [
            [KeyboardButton(BTN_VPN_MENU)],
        ]
        return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(BTN_START)],
        [KeyboardButton(BTN_VPN_MENU), KeyboardButton(BTN_REGISTER)],
    ]
    if is_admin:
        rows.append([KeyboardButton(BTN_ADMIN_MENU)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def normalize_text(text: str | None) -> str:
    return (text or "").strip()

