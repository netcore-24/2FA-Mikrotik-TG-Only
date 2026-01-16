from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.error import TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from mikrotik_2fa_bot.config import settings
from mikrotik_2fa_bot.db import init_db
from mikrotik_2fa_bot.db import db_session
from mikrotik_2fa_bot.handlers.basic import start_cmd, help_cmd, whoami_cmd, unknown_command_cmd, fallback_text_cmd
from mikrotik_2fa_bot.handlers.registration import (
    REGISTER_FULLNAME,
    register_cmd,
    register_fullname,
    cancel_cmd,
)
from mikrotik_2fa_bot.handlers.user import request_vpn_cmd, my_sessions_cmd, disable_vpn_cmd
from mikrotik_2fa_bot.handlers.admin import (
    pending_cmd,
    approve_cmd,
    reject_cmd,
    bind_cmd,
    unbind_cmd,
    set_fw_comment_cmd,
    create_user_cmd,
    test_router_cmd,
    admin_sessions_cmd,
    restart_bot_cmd,
    add_admin_cmd,
    remove_admin_cmd,
    list_admins_cmd,
)
from mikrotik_2fa_bot.handlers.callbacks import callback_handler
from mikrotik_2fa_bot.services import scheduler as scheduler_service
from mikrotik_2fa_bot.services.app_settings import apply_router_overrides_to_runtime_settings
from mikrotik_2fa_bot.handlers.admin_users_panel import admin_users_panel_cmd
from mikrotik_2fa_bot.handlers.um_link import (
    um_link_start,
    um_link_callback,
    CHOOSE_TG,
    CHOOSE_UM,
)
from mikrotik_2fa_bot.handlers.firewall import firewall_list_cmd
from mikrotik_2fa_bot.handlers.user_settings import (
    user_settings_start,
    user_settings_callback,
    US_CHOOSE_USER,
    US_ACTION,
    US_CHOOSE_UM,
    US_CHOOSE_FW,
)
from mikrotik_2fa_bot.handlers.menu import (
    normalize_text,
    BTN_START,
    BTN_HELP,
    BTN_WHOAMI,
    BTN_REGISTER,
    BTN_VPN_MENU,
    BTN_ADMIN_MENU,
    BTN_ADMIN_ROUTER_SETTINGS,
    BTN_ADMIN_ROUTER_TEST,
)
from mikrotik_2fa_bot.handlers.registration import register_cmd
from mikrotik_2fa_bot.handlers.user import request_vpn_cmd, my_sessions_cmd, disable_vpn_cmd
from mikrotik_2fa_bot.handlers.util import is_admin
from mikrotik_2fa_bot.handlers.router_settings import (
    router_settings_cmd,
    router_settings_callback,
    router_settings_value,
    CHOOSE_FIELD,
    ENTER_VALUE,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Avoid leaking bot token via httpx request logs (URL contains the token).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        if isinstance(context.error, TimedOut):
            return
        logger.error("Bot error: %s", context.error, exc_info=True)
    except Exception:
        logger.error("Error in error handler", exc_info=True)


async def main():
    init_db()
    # Load router settings overrides from DB (so admin can change them via Telegram).
    with db_session() as db:
        apply_router_overrides_to_runtime_settings(db, settings)

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    request = HTTPXRequest(connect_timeout=15, read_timeout=45, write_timeout=45, pool_timeout=15)
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami_cmd))

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("register", register_cmd),
                # allow starting from ReplyKeyboard button
                MessageHandler(filters.Regex(rf"^{BTN_REGISTER}$"), register_cmd),
            ],
            states={REGISTER_FULLNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_fullname)]},
            fallbacks=[CommandHandler("cancel", cancel_cmd)],
        )
    )

    app.add_handler(CommandHandler("request_vpn", request_vpn_cmd))
    app.add_handler(CommandHandler("my_sessions", my_sessions_cmd))
    app.add_handler(CommandHandler("disable_vpn", disable_vpn_cmd))

    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("reject", reject_cmd))
    app.add_handler(CommandHandler("bind", bind_cmd))
    app.add_handler(CommandHandler("unbind", unbind_cmd))
    app.add_handler(CommandHandler("set_fw_comment", set_fw_comment_cmd))
    app.add_handler(CommandHandler("create_user", create_user_cmd))
    app.add_handler(CommandHandler("test_router", test_router_cmd))
    app.add_handler(CommandHandler("sessions", admin_sessions_cmd))
    app.add_handler(CommandHandler("restart_bot", restart_bot_cmd))
    app.add_handler(CommandHandler("add_admin", add_admin_cmd))
    app.add_handler(CommandHandler("remove_admin", remove_admin_cmd))
    app.add_handler(CommandHandler("list_admins", list_admins_cmd))
    app.add_handler(CommandHandler("firewall", firewall_list_cmd))

    # Router settings conversation (inline keyboard + text input)
    app.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("router_settings", router_settings_cmd),
                # allow starting from ReplyKeyboard button
                MessageHandler(filters.Regex(rf"^{BTN_ADMIN_ROUTER_SETTINGS}$"), router_settings_cmd),
                # allow starting from Admin panel inline button
                CallbackQueryHandler(router_settings_cmd, pattern=r"^admin_panel:router_settings$"),
            ],
            states={
                CHOOSE_FIELD: [CallbackQueryHandler(router_settings_callback, pattern=r"^rs:")],
                ENTER_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, router_settings_value)],
            },
            fallbacks=[CommandHandler("cancel", cancel_cmd)],
        )
    )

    # UM link conversation (admin)
    app.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("link_um", um_link_start),
                CallbackQueryHandler(um_link_start, pattern=r"^admin_panel:link_um$"),
            ],
            states={
                CHOOSE_TG: [CallbackQueryHandler(um_link_callback, pattern=r"^(tg_page:|tg_pick:|um_cancel$)")],
                CHOOSE_UM: [CallbackQueryHandler(um_link_callback, pattern=r"^(um_page:|um_pick_id:|um_cancel$)")],
            },
            fallbacks=[CommandHandler("cancel", cancel_cmd)],
        )
    )

    # User settings conversation (admin): per-user 2FA + firewall rule + UM binding
    app.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("user_settings", user_settings_start),
                CallbackQueryHandler(user_settings_start, pattern=r"^admin_panel:user_settings$"),
            ],
            states={
                US_CHOOSE_USER: [CallbackQueryHandler(user_settings_callback, pattern=r"^(us_user_page:|us_user_pick:|us_cancel$)")],
                US_ACTION: [CallbackQueryHandler(user_settings_callback, pattern=r"^(us_action:|us_back:|us_cancel$)")],
                US_CHOOSE_UM: [CallbackQueryHandler(user_settings_callback, pattern=r"^(us_um_page:|us_um_pick_id:|us_back:|us_cancel$)")],
                US_CHOOSE_FW: [CallbackQueryHandler(user_settings_callback, pattern=r"^(us_fw_page:|us_fw_pick_id:|us_back:|us_cancel$)")],
            },
            fallbacks=[CommandHandler("cancel", cancel_cmd)],
        )
    )

    # Callback router for inline buttons (MUST be after conversations, otherwise it steals callbacks)
    app.add_handler(CallbackQueryHandler(callback_handler))
    # ReplyKeyboard menu routing (text buttons)
    async def _menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        txt = normalize_text(update.message.text if update.message else "")
        uid = update.effective_user.id
        chat_id = update.effective_chat.id
        username = getattr(update.effective_user, "username", None)
        admin = is_admin(chat_id, uid, username)

        if txt == BTN_START:
            return await start_cmd(update, context)
        if txt == BTN_HELP:
            return await help_cmd(update, context)
        if txt == BTN_WHOAMI:
            return await whoami_cmd(update, context)
        if txt == BTN_VPN_MENU:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("🔑 Запросить VPN", callback_data="menu_vpn:request"),
                    InlineKeyboardButton("📡 Мои сессии", callback_data="menu_vpn:sessions"),
                ], [
                    InlineKeyboardButton("⛔ Отключить VPN", callback_data="menu_vpn:disable"),
                ]]
            )
            return await update.message.reply_text("VPN меню:", reply_markup=kb)

        if admin and txt == BTN_ADMIN_MENU:
            return await admin_users_panel_cmd(update, context)
        if admin and txt == BTN_ADMIN_ROUTER_TEST:
            return await test_router_cmd(update, context)
        if admin and txt == BTN_ADMIN_ROUTER_SETTINGS:
            return await router_settings_cmd(update, context)

        return await fallback_text_cmd(update, context)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _menu_router))
    # UX/debug: respond to unknown commands and plain text
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command_cmd))
    app.add_error_handler(error_handler)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduler_service.poll_once,
        trigger=IntervalTrigger(seconds=int(settings.POLL_INTERVAL_SECONDS)),
        args=[app.bot],
        id="poll_mikrotik",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    await app.initialize()
    await app.start()
    scheduler.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    logger.info("Bot started.")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


