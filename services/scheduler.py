"""
APScheduler jobs for WODpilot.

Jobs:
  1. Daily Garmin sync (05:00)
  2. WOD scraping (05:30)
  3. Morning briefing dispatch (07:00)
  4. Weekly planning question (Sunday 10:00)
  5. Weekly planning fallback for users who didn't reply (Sunday 18:00)

All jobs run on server time; users.timezone is not taken into account
(same simplification as the morning briefing).
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
    from services.pi_agent_client import generate_morning_briefing

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
            from utils.telegram import send_safe
            await send_safe(
                lambda t, **kw: app.bot.send_message(chat_id=u["telegram_id"], text=t, **kw),
                f"☀️ *Morgendliches Briefing*\n\n{briefing[:4000]}",
            )
        except Exception as exc:
            logger.error("Morning briefing failed for user %s: %s", u["id"], exc)


async def job_weekly_plan_ask(app: "Application") -> None:
    """Ask every athlete on Sunday whether anything affects the coming week."""
    from db.client import get_db
    from services.planning import mark_week_asked, upcoming_week_start

    db = get_db()
    users = (
        db.table("users")
        .select("id,telegram_id,full_name,username")
        .not_.is_("llm_api_key_enc", "null")
        .execute()
    ).data or []

    week_start = upcoming_week_start()
    logger.info("Asking %d users about the week starting %s", len(users), week_start)
    for u in users:
        try:
            # None means the week is already being planned – don't ask twice.
            if mark_week_asked(u["id"], week_start) is None:
                continue
            await app.bot.send_message(
                chat_id=u["telegram_id"],
                text=(
                    "🗓️ *Wochenplanung*\n\n"
                    f"Ich plane gleich deine Woche ab Montag, {week_start.strftime('%d.%m.')}. "
                    "Gibt es Termine, Einschränkungen oder Wünsche, die ich berücksichtigen soll?\n\n"
                    "Antworte einfach hier – oder ich plane heute Abend anhand deiner Präferenzen."
                ),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.error("Weekly plan question failed for user %s: %s", u["id"], exc)


async def job_weekly_plan_fallback(app: "Application") -> None:
    """Plan the week for everyone who didn't reply to the Sunday question."""
    from db.client import get_db
    from services.pi_agent_client import generate_week_plan
    from services.planning import claim_planning, upcoming_week_start, users_awaiting_plan

    week_start = upcoming_week_start()
    pending = users_awaiting_plan(week_start)
    if not pending:
        return

    db = get_db()
    logger.info("Fallback planning for %d users", len(pending))
    for plan in pending:
        try:
            # The user may have replied in the meantime – then their message
            # already claimed the week and we must not plan it again.
            if not claim_planning(plan["id"]):
                continue
            user = (
                db.table("users")
                .select("id,telegram_id,full_name,username")
                .eq("id", plan["user_id"])
                .single()
                .execute()
            ).data
            if not user:
                continue
            name = user.get("full_name") or user.get("username") or "Athlet"
            summary = await generate_week_plan(
                user["id"], name, constraints=None, plan_id=plan["id"],
                week_start=str(plan["week_start"]),
            )
            from utils.telegram import send_safe
            await send_safe(
                lambda t, **kw: app.bot.send_message(chat_id=user["telegram_id"], text=t, **kw),
                f"🗓️ *Deine Woche*\n\n{summary[:4000]}",
            )
        except Exception as exc:
            logger.error("Fallback planning failed for plan %s: %s", plan["id"], exc)


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

    # Weekly planning – ask on Sunday morning
    scheduler.add_job(
        lambda: asyncio.ensure_future(job_weekly_plan_ask(app)),
        trigger=CronTrigger(**_parse_cron(cfg.weekly_plan_ask_cron)),
        id="weekly_plan_ask",
        replace_existing=True,
    )

    # Weekly planning – plan without a reply on Sunday evening
    scheduler.add_job(
        lambda: asyncio.ensure_future(job_weekly_plan_fallback(app)),
        trigger=CronTrigger(**_parse_cron(cfg.weekly_plan_fallback_cron)),
        id="weekly_plan_fallback",
        replace_existing=True,
    )

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))
    return scheduler
