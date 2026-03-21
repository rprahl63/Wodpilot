"""
APScheduler jobs for WODpilot.

Jobs:
  1. Daily Garmin sync (05:00)
  2. WOD scraping (05:30)
  3. Morning briefing dispatch (07:00)
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_config

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)


async def job_garmin_sync() -> None:
    """Sync Garmin activities for all users with Garmin credentials."""
    from db.client import get_db
    from services.garmin import sync_user_activities

    db = get_db()
    users = (
        db.table("users")
        .select("id")
        .not_.is_("garmin_email", "null")
        .execute()
    ).data or []

    total = 0
    for u in users:
        try:
            count = sync_user_activities(u["id"])
            total += count
        except Exception as exc:
            logger.error("Garmin sync failed for user %s: %s", u["id"], exc)

    logger.info("Garmin sync complete: %d activities synced across %d users", total, len(users))


async def job_wod_scrape() -> None:
    """Scrape WODs from all configured sources."""
    from services.scraper import scrape_all_wods

    try:
        count = scrape_all_wods()
        logger.info("WOD scrape complete: %d WODs scraped", count)
    except Exception as exc:
        logger.error("WOD scrape failed: %s", exc)


async def job_morning_briefing(app: "Application") -> None:
    """Send morning briefings to all opted-in users."""
    from db.client import get_db
    from agent.coach import generate_morning_briefing

    db = get_db()
    users = (
        db.table("users")
        .select("id,telegram_id,full_name,username,llm_api_key_enc")
        .eq("briefing_enabled", True)
        .not_.is_("llm_api_key_enc", "null")
        .execute()
    ).data or []

    logger.info("Sending morning briefings to %d users", len(users))
    for u in users:
        try:
            name = u.get("full_name") or u.get("username") or "Athlet"
            briefing = await generate_morning_briefing(u["id"], name)
            await app.bot.send_message(
                chat_id=u["telegram_id"],
                text=f"☀️ *Morgendliches Briefing*\n\n{briefing[:4000]}",
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.error("Morning briefing failed for user %s: %s", u["id"], exc)


def setup_scheduler(app: "Application") -> AsyncIOScheduler:
    """Create and configure the APScheduler instance."""
    cfg = get_config()
    scheduler = AsyncIOScheduler()

    def _parse_cron(expr: str) -> dict:
        parts = expr.split()
        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }

    # Garmin sync
    scheduler.add_job(
        job_garmin_sync,
        trigger=CronTrigger(**_parse_cron(cfg.garmin_sync_cron)),
        id="garmin_sync",
        replace_existing=True,
    )

    # WOD scrape
    scheduler.add_job(
        job_wod_scrape,
        trigger=CronTrigger(**_parse_cron(cfg.wod_scrape_cron)),
        id="wod_scrape",
        replace_existing=True,
    )

    # Morning briefing – needs the Telegram app
    scheduler.add_job(
        lambda: asyncio.ensure_future(job_morning_briefing(app)),
        trigger=CronTrigger(**_parse_cron(cfg.morning_briefing_cron)),
        id="morning_briefing",
        replace_existing=True,
    )

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))
    return scheduler
