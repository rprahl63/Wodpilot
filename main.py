"""
WODpilot Bot – main entry point.
Starts the Telegram bot + APScheduler in a single async process.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from telegram.ext import Application, CallbackQueryHandler

from bot.handlers import get_handlers, handle_delete_callback
from bot.registration import get_registration_handler
from config import get_config
from services.scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def run() -> None:
    cfg = get_config()
    logger.info("Starting WODpilot bot…")

    app = Application.builder().token(cfg.telegram_token).build()

    # Registration flow (must be first)
    app.add_handler(get_registration_handler())

    # Delete confirmation callback
    app.add_handler(
        CallbackQueryHandler(handle_delete_callback, pattern="^delete_")
    )

    # Regular handlers
    for handler in get_handlers():
        app.add_handler(handler)

    # Scheduler
    scheduler = setup_scheduler(app)
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot is running. Press Ctrl+C to stop.")

    # Keep running until interrupted
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
