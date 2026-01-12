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
from mikrotik_2fa_bot.handlers.basic import start_cmd, help_cmd
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
)
from mikrotik_2fa_bot.handlers.callbacks import callback_handler
from mikrotik_2fa_bot.services import scheduler as scheduler_service


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        if isinstance(context.error, TimedOut):
            return
        logger.error("Bot error: %s", context.error, exc_info=True)
    except Exception:
        logger.error("Error in error handler", exc_info=True)


async def main():
    init_db()

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    request = HTTPXRequest(connect_timeout=15, read_timeout=45, write_timeout=45, pool_timeout=15)
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("register", register_cmd)],
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

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduler_service.poll_once,
        trigger=IntervalTrigger(seconds=int(settings.POLL_INTERVAL_SECONDS)),
        args=[app.bot],
        id="poll_mikrotik",
        replace_existing=True,
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


