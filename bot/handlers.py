"""
Main Telegram message handlers (post-registration).
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db.client import get_db

logger = logging.getLogger(__name__)


def _get_user(telegram_id: int) -> Optional[dict]:
    db = get_db()
    result = (
        db.table("users")
        .select("id,full_name,username,role,garmin_email")
        .eq("telegram_id", telegram_id)
        .execute()
    ).data
    return result[0] if result else None


async def _require_user(update: Update) -> Optional[dict]:
    user = _get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "Du bist noch nicht registriert. Starte mit /start."
        )
        return None
    return user


async def _process_text(update: Update, user: dict, text: str) -> None:
    """
    Route a user utterance to the agent and reply.

    Shared by text and voice messages so a spoken answer to the Sunday
    planning question is treated exactly like a typed one.
    """
    name = user["full_name"] or user["username"] or "Athlet"

    # A pending Sunday question turns the next message into planning input.
    # Claiming here means a message racing the fallback job just becomes a
    # normal chat message instead of planning the week a second time.
    # This runs on every message, so a planning-side failure must never cost
    # the athlete their chat – degrade to a normal conversation instead.
    pending = None
    try:
        from services.planning import claim_planning, get_pending_ask
        pending = get_pending_ask(user["id"])
        if pending and not claim_planning(pending["id"], text):
            pending = None
    except Exception as exc:
        logger.error("Planning lookup failed for user %s: %s", user["id"], exc)
        pending = None

    thinking_msg = await update.message.reply_text(
        "🗓️ Plane deine Woche…" if pending else "⏳ Denke nach…"
    )

    try:
        if pending:
            from services.pi_agent_client import generate_week_plan
            response = await generate_week_plan(
                user_id=user["id"],
                user_name=name,
                constraints=text,
                plan_id=pending["id"],
                week_start=str(pending["week_start"]),
            )
        else:
            from services.pi_agent_client import chat
            response = await chat(
                user_id=user["id"],
                user_name=name,
                message=text,
            )
    except ValueError as exc:
        response = f"⚠️ {exc}"
    except Exception as exc:
        logger.exception("Agent error for user %s: %s", user["id"], exc)
        response = "❌ Interner Fehler. Bitte versuche es erneut."

    await thinking_msg.delete()
    # Telegram max message length is 4096
    if len(response) > 4096:
        for i in range(0, len(response), 4096):
            await update.message.reply_text(response[i : i + 4096])
    else:
        await update.message.reply_text(response)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages – route to coach agent."""
    user = await _require_user(update)
    if not user:
        return

    await _process_text(update, user, update.message.text)


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a voice message and treat it like a typed message."""
    user = await _require_user(update)
    if not user:
        return

    media = update.message.voice or update.message.audio
    if not media:
        return

    from services.transcription import MAX_AUDIO_BYTES, transcribe

    if media.file_size and media.file_size > MAX_AUDIO_BYTES:
        await update.message.reply_text(
            "❌ Sprachnachricht zu lang. Bitte teile sie in kürzere Abschnitte auf."
        )
        return

    thinking_msg = await update.message.reply_text("🎙️ Höre zu…")
    try:
        file = await ctx.bot.get_file(media.file_id)
        audio_bytes = bytes(await file.download_as_bytearray())
        text = await transcribe(
            audio_bytes, user_id=user["id"], mime_type=getattr(media, "mime_type", None)
        )
    except Exception as exc:
        logger.exception("Voice download failed for user %s: %s", user["id"], exc)
        text = None

    await thinking_msg.delete()

    if not text:
        await update.message.reply_text(
            "❌ Ich konnte die Sprachnachricht nicht verstehen. "
            "Versuch es nochmal oder schreib mir kurz."
        )
        return

    # Echo the transcript so a mis-heard message is obvious to the athlete.
    await update.message.reply_text(f"🎙️ _{text}_", parse_mode="Markdown")
    await _process_text(update, user, text)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages – analyze via Claude Vision."""
    user = await _require_user(update)
    if not user:
        return

    thinking_msg = await update.message.reply_text("📸 Analysiere Bild…")

    try:
        # Get highest-res photo
        photo = update.message.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())
        caption = update.message.caption or ""

        from services.pi_agent_client import analyze_image
        response = await analyze_image(
            user_id=user["id"],
            user_name=user["full_name"] or "Athlet",
            image_bytes=image_bytes,
            caption=caption,
        )
    except Exception as exc:
        logger.exception("Image analysis error: %s", exc)
        response = "❌ Bild-Analyse fehlgeschlagen."

    await thinking_msg.delete()
    await update.message.reply_text(response)


async def handle_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle video messages – extract frames and analyze."""
    user = await _require_user(update)
    if not user:
        return

    # Check file size (50MB Telegram limit)
    video = update.message.video
    if video and video.file_size and video.file_size > 50 * 1024 * 1024:
        await update.message.reply_text(
            "❌ Video zu groß (max 50MB). Bitte kürze das Video."
        )
        return

    thinking_msg = await update.message.reply_text("🎬 Analysiere Video (extrahiere Frames)…")

    try:
        file = await ctx.bot.get_file(video.file_id)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        caption = update.message.caption or ""
        from services.pi_agent_client import analyze_video
        response = await analyze_video(
            user_id=user["id"],
            user_name=user["full_name"] or "Athlet",
            video_path=tmp_path,
            caption=caption,
        )
        os.unlink(tmp_path)
    except Exception as exc:
        logger.exception("Video analysis error: %s", exc)
        response = "❌ Video-Analyse fehlgeschlagen."

    await thinking_msg.delete()
    await update.message.reply_text(response)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*WODpilot Befehle*\n\n"
        "/start – Registrierung\n"
        "/help – Diese Hilfe\n"
        "/status – Dein aktueller Trainingsstatus (ATL/CTL/TSB)\n"
        "/prs – Deine Personal Records\n"
        "/wod – Heutiges WOD\n"
        "/briefing – Morgendliches Briefing jetzt\n"
        "/dashboard – Login-Link zu deinem Wochenplan\n"
        "/replan – Woche neu planen (`next` oder Datum für eine andere Woche)\n"
        "/settings – Deine Einstellungen\n"
        "/delete – Account löschen (DSGVO)\n\n"
        "Schreib mir einfach, schick mir eine Sprachnachricht oder ein Video – "
        "ich bin dein Coach! 💪",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if not user:
        return

    msg = await update.message.reply_text("📊 Lade Trainingsstatus…")
    try:
        from services.garmin import get_training_load
        load = get_training_load(user["id"])
        text = (
            f"📊 *Dein Trainingsstatus*\n\n"
            f"ATL (Müdigkeit): `{load.atl}`\n"
            f"CTL (Fitness): `{load.ctl}`\n"
            f"TSB (Form): `{load.tsb}`\n"
            f"Woche TSS: `{load.weekly_tss}`\n"
            f"Lauf 14d: `{load.run_km_14d} km`\n\n"
            f"💡 {load.recommendation}"
        )
    except Exception as exc:
        text = f"Fehler beim Laden: {exc}"
    await msg.edit_text(text, parse_mode="Markdown")


async def cmd_prs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if not user:
        return

    from memory.episodic import get_prs
    prs = get_prs(user["id"])
    if not prs:
        await update.message.reply_text("Noch keine PRs gespeichert. Erzähl mir von deinen Bestleistungen!")
        return

    lines = ["🏆 *Deine Personal Records*\n"]
    for pr in prs[:20]:
        lines.append(f"• {pr['content']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_wod(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if not user:
        return

    msg = await update.message.reply_text("🏋️ Lade heutige WODs…")
    from services.scraper import get_todays_wods
    wods = get_todays_wods()
    if not wods:
        await msg.edit_text("Keine WODs für heute verfügbar. Frag mich nach einem individuellen Workout!")
        return

    lines = ["📋 *Heutige WODs*\n"]
    for w in wods:
        lines.append(f"*{w['source']}*\n{w['content'][:500]}\n")
    await msg.edit_text("\n".join(lines)[:4096], parse_mode="Markdown")


async def cmd_briefing(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if not user:
        return

    msg = await update.message.reply_text("☀️ Erstelle dein Briefing…")
    try:
        from services.pi_agent_client import generate_morning_briefing
        response = await generate_morning_briefing(
            user_id=user["id"],
            user_name=user["full_name"] or "Athlet",
        )
    except ValueError as exc:
        response = f"⚠️ {exc}"
    except Exception as exc:
        logger.exception("Briefing error: %s", exc)
        response = "❌ Briefing fehlgeschlagen."
    await msg.edit_text(response[:4096])


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if not user:
        return

    await update.message.reply_text(
        "⚙️ *Einstellungen*\n\n"
        "Deinen Wochenplan und deine Trainingspräferenzen pflegst du im Dashboard – "
        "hol dir mit /dashboard einen Login-Link.\n\n"
        "Über das Admin-Dashboard änderbar:\n"
        "• Anthropic API-Key\n"
        "• Garmin-Zugangsdaten\n"
        "• HR-Profil (Max HR, Resting HR)\n"
        "• Bevorzugtes Modell\n"
        "• Benachrichtigungs-Einstellungen",
        parse_mode="Markdown",
    )


async def cmd_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a single-use magic link to the athlete dashboard."""
    user = await _require_user(update)
    if not user:
        return

    from config import get_config
    from services.login_tokens import create_login_token

    cfg = get_config()
    try:
        token = create_login_token(user["id"])
    except Exception as exc:
        logger.exception("Could not create login token for user %s: %s", user["id"], exc)
        await update.message.reply_text("❌ Login-Link konnte nicht erstellt werden.")
        return

    await update.message.reply_text(
        "🔗 *Dein Dashboard*\n\n"
        f"{cfg.dashboard_base_url}/me/auth/{token}\n\n"
        f"Der Link ist {cfg.login_token_ttl_minutes} Minuten gültig und nur einmal nutzbar.\n"
        "Dort siehst du deinen Wochenplan, trägst Ergebnisse ein und pflegst deine "
        "Trainingspräferenzen.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


_NEXT_WEEK_WORDS = {"next", "nächste", "naechste", "kommende"}


def parse_replan_args(args: list[str] | None) -> tuple[object, str | None]:
    """
    Split /replan arguments into (week_start, constraints).

    Defaults to the *current* week – mid-week you usually want to fix the week
    you are in. A leading "next"/"nächste" or an ISO date picks another week;
    everything else is treated as constraints for the planner.
    """
    from datetime import date as _date

    from services.planning import current_week_start, upcoming_week_start

    args = list(args or [])
    week = current_week_start()

    if args:
        head = args[0].lower().strip(",")
        if head in _NEXT_WEEK_WORDS:
            week = upcoming_week_start()
            args = args[1:]
        else:
            try:
                week = current_week_start(_date.fromisoformat(head))
                args = args[1:]
            except ValueError:
                pass

    constraints = " ".join(args).strip() or None
    return week, constraints


async def cmd_replan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Plan a week on demand, overwriting an existing plan.

    `/replan` plans the current week, `/replan next` the coming one, and
    `/replan 2026-07-27` a specific one. Any remaining text becomes the
    constraints handed to the planner.
    """
    user = await _require_user(update)
    if not user:
        return

    from services.pi_agent_client import generate_week_plan
    from services.planning import claim_replan

    week_start, constraints = parse_replan_args(ctx.args)

    msg = await update.message.reply_text(
        f"🗓️ Plane deine Woche ab {week_start.strftime('%d.%m.')}…"
    )
    try:
        plan = claim_replan(user["id"], week_start, constraints)
        if plan is None:
            await msg.edit_text("Diese Woche wird gerade schon geplant – einen Moment.")
            return
        response = await generate_week_plan(
            user_id=user["id"],
            user_name=user["full_name"] or user["username"] or "Athlet",
            constraints=constraints,
            plan_id=plan["id"],
            week_start=week_start.isoformat(),
        )
    except ValueError as exc:
        response = f"⚠️ {exc}"
    except Exception as exc:
        logger.exception("Replan error for user %s: %s", user["id"], exc)
        response = "❌ Wochenplanung fehlgeschlagen."
    await msg.edit_text(response[:4096])


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if not user:
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = [[
        InlineKeyboardButton("🗑️ Ja, alles löschen", callback_data=f"delete_confirm_{user['id']}"),
        InlineKeyboardButton("❌ Abbrechen", callback_data="delete_cancel"),
    ]]
    await update.message.reply_text(
        "⚠️ *Account löschen (DSGVO Widerruf)*\n\n"
        "Alle deine Daten werden unwiderruflich gelöscht:\n"
        "• Trainingsdaten\n"
        "• Konversationsverlauf\n"
        "• Memory (PRs, Verletzungen, etc.)\n"
        "• Garmin-Credentials\n"
        "• API-Key\n\n"
        "Bist du sicher?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_delete_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "delete_cancel":
        await query.edit_message_text("Account-Löschung abgebrochen.")
        return

    if query.data.startswith("delete_confirm_"):
        user_id = int(query.data.split("_")[-1])
        db = get_db()
        db.table("users").delete().eq("id", user_id).execute()
        await query.edit_message_text(
            "✅ Alle deine Daten wurden gelöscht. Auf Wiedersehen!"
        )


def get_handlers():
    """Return all post-registration handlers."""
    return [
        CommandHandler("help", cmd_help),
        CommandHandler("status", cmd_status),
        CommandHandler("prs", cmd_prs),
        CommandHandler("wod", cmd_wod),
        CommandHandler("briefing", cmd_briefing),
        CommandHandler("dashboard", cmd_dashboard),
        CommandHandler("replan", cmd_replan),
        CommandHandler("settings", cmd_settings),
        CommandHandler("delete", cmd_delete),
        MessageHandler(filters.PHOTO, handle_photo),
        MessageHandler(filters.VIDEO, handle_video),
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
    ]
