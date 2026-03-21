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


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages – route to coach agent."""
    user = await _require_user(update)
    if not user:
        return

    text = update.message.text
    thinking_msg = await update.message.reply_text("⏳ Denke nach…")

    try:
        from agent.coach import chat
        response = await chat(
            user_id=user["id"],
            user_name=user["full_name"] or user["username"] or "Athlet",
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

        from agent.coach import analyze_image
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
        from agent.coach import analyze_video
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
        "/settings – Deine Einstellungen\n"
        "/delete – Account löschen (DSGVO)\n\n"
        "Oder schreib mir einfach – ich bin dein Coach! 💪",
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
        from agent.coach import generate_morning_briefing
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
        "Verwalte dein Profil im Web-Dashboard:\n"
        "_(URL vom Admin erfragen)_\n\n"
        "Du kannst dort ändern:\n"
        "• Anthropic API-Key\n"
        "• Garmin-Zugangsdaten\n"
        "• HR-Profil (Max HR, Resting HR)\n"
        "• Bevorzugtes Modell\n"
        "• Benachrichtigungs-Einstellungen",
        parse_mode="Markdown",
    )


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
        CommandHandler("settings", cmd_settings),
        CommandHandler("delete", cmd_delete),
        MessageHandler(filters.PHOTO, handle_photo),
        MessageHandler(filters.VIDEO, handle_video),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
    ]
