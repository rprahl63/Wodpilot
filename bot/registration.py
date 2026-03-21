"""
Telegram ConversationHandler for user registration.

Flow:
  /start → INVITE_CODE → CHECK_CONSENT → GARMIN_EMAIL → GARMIN_PASS → API_KEY → DONE
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db.client import get_db
from utils.crypto import encrypt

logger = logging.getLogger(__name__)

# Conversation states
(
    INVITE_CODE,
    CHECK_CONSENT,
    GARMIN_EMAIL,
    GARMIN_PASS,
    API_KEY,
    LLM_MODEL,
) = range(6)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    db = get_db()
    tg_id = update.effective_user.id

    # Already registered?
    existing = (
        db.table("users").select("id,role").eq("telegram_id", tg_id).execute()
    ).data
    if existing:
        await update.message.reply_text(
            "👋 Willkommen zurück! Schreib mir einfach – ich bin dein Coach.\n"
            "/help für alle Befehle."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🏋️ *Willkommen bei WODpilot!*\n\n"
        "Dein KI-gestützter CrossFit Remote Coach.\n\n"
        "Um fortzufahren, benötigst du einen *Einladungscode*.\n"
        "Bitte gib deinen Code ein:",
        parse_mode="Markdown",
    )
    return INVITE_CODE


async def receive_invite_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    db = get_db()

    row = (
        db.table("invite_codes")
        .select("id,expires_at,used_by")
        .eq("code", code)
        .execute()
    ).data

    if not row:
        await update.message.reply_text(
            "❌ Ungültiger Code. Bitte versuche es erneut oder kontaktiere den Admin."
        )
        return INVITE_CODE

    invite = row[0]
    if invite.get("used_by"):
        await update.message.reply_text("❌ Dieser Code wurde bereits verwendet.")
        return INVITE_CODE

    if invite.get("expires_at"):
        exp = datetime.fromisoformat(invite["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            await update.message.reply_text("❌ Dieser Code ist abgelaufen.")
            return INVITE_CODE

    ctx.user_data["invite_code_id"] = invite["id"]

    keyboard = [
        [
            InlineKeyboardButton("✅ Ich stimme zu", callback_data="consent_yes"),
            InlineKeyboardButton("❌ Ablehnen", callback_data="consent_no"),
        ]
    ]
    await update.message.reply_text(
        "📋 *Datenschutz & Nutzungsbedingungen*\n\n"
        "WODpilot verarbeitet deine Gesundheitsdaten (Trainingsdaten, HR) gemäß DSGVO Art. 9.\n\n"
        "⚠️ *Wichtiger Hinweis:* WODpilot ist kein medizinischer Dienst. "
        "Alle Trainingsempfehlungen erfolgen ohne Gewähr. Du trainierst auf eigene Verantwortung.\n\n"
        "• Ich bin mindestens 18 Jahre alt\n"
        "• Ich wurde sportmedizinisch freigegeben\n"
        "• Ich verstehe, dass dies kein medizinischer Dienst ist\n"
        "• Ich stimme den AGB und der Datenschutzerklärung zu\n\n"
        "Stimmst du zu?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHECK_CONSENT


async def receive_consent(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "consent_no":
        await query.edit_message_text(
            "Schade! Du kannst WODpilot nicht ohne Zustimmung nutzen. "
            "Starte neu mit /start wenn du es dir anders überlegst."
        )
        return ConversationHandler.END

    ctx.user_data["consent_given"] = True
    await query.edit_message_text(
        "✅ Danke! Jetzt verbinden wir Garmin Connect.\n\n"
        "Gib deine *Garmin Connect E-Mail* ein\n"
        "(oder /skip um Garmin später einzurichten):",
        parse_mode="Markdown",
    )
    return GARMIN_EMAIL


async def receive_garmin_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() != "/skip":
        ctx.user_data["garmin_email"] = text
        await update.message.reply_text(
            "🔒 Gib dein *Garmin Connect Passwort* ein:\n"
            "_(wird AES-verschlüsselt gespeichert)_",
            parse_mode="Markdown",
        )
        return GARMIN_PASS

    ctx.user_data["garmin_email"] = None
    await update.message.reply_text(
        "Garmin übersprungen.\n\n"
        "Jetzt zum wichtigsten: dein *Anthropic API-Key*.\n"
        "Hole ihn von https://console.anthropic.com/settings/keys\n\n"
        "Format: `sk-ant-...`",
        parse_mode="Markdown",
    )
    return API_KEY


async def receive_garmin_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    # Delete the message immediately for security
    try:
        await update.message.delete()
    except Exception:
        pass

    ctx.user_data["garmin_password"] = password
    await update.effective_chat.send_message(
        "✅ Garmin-Passwort gespeichert (verschlüsselt).\n\n"
        "Jetzt dein *Anthropic API-Key*:\n"
        "Hole ihn von https://console.anthropic.com/settings/keys\n\n"
        "Format: `sk-ant-...`",
        parse_mode="Markdown",
    )
    return API_KEY


async def receive_api_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    api_key = update.message.text.strip()
    # Delete for security
    try:
        await update.message.delete()
    except Exception:
        pass

    if not api_key.startswith("sk-ant-"):
        await update.effective_chat.send_message(
            "❌ Das sieht nicht wie ein gültiger Anthropic API-Key aus (muss mit `sk-ant-` beginnen).\n"
            "Versuche es erneut:",
            parse_mode="Markdown",
        )
        return API_KEY

    ctx.user_data["api_key"] = api_key
    await update.effective_chat.send_message(
        "✅ API-Key gespeichert.\n\n"
        "Welches *Modell* möchtest du verwenden?\n"
        "Standard: `claude-sonnet-4-20250514`\n"
        "Alternativ: `claude-opus-4-20250514` (teurer, stärker)\n\n"
        "Einfach Enter drücken für Standard oder Modell-Name eingeben:",
        parse_mode="Markdown",
    )
    return LLM_MODEL


async def receive_llm_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    model = text if text.startswith("claude-") else "claude-sonnet-4-20250514"
    ctx.user_data["llm_model"] = model

    return await _finalize_registration(update, ctx)


async def _finalize_registration(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    db = get_db()
    tg_user = update.effective_user
    ud = ctx.user_data

    # Encrypt secrets
    garmin_email = ud.get("garmin_email")
    garmin_pass = ud.get("garmin_password")
    api_key = ud.get("api_key", "")

    record = {
        "telegram_id": tg_user.id,
        "username": tg_user.username,
        "full_name": tg_user.full_name,
        "role": "user",
        "llm_api_key_enc": encrypt(api_key) if api_key else None,
        "llm_model": ud.get("llm_model", "claude-sonnet-4-20250514"),
        "garmin_email": garmin_email,
        "garmin_password_enc": encrypt(garmin_pass) if garmin_pass else None,
        "consent_given_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.table("users").insert(record).execute()
    new_user_id = result.data[0]["id"]

    # Mark invite code as used
    if invite_id := ud.get("invite_code_id"):
        db.table("invite_codes").update({"used_by": new_user_id}).eq("id", invite_id).execute()

    # Initialize procedural memory
    db.table("memory_procedural").upsert(
        {"user_id": new_user_id, "coaching_style": "balanced", "preferred_language": "de"},
        on_conflict="user_id",
    ).execute()

    await update.message.reply_text(
        f"🎉 *Registrierung abgeschlossen!*\n\n"
        f"Willkommen, {tg_user.first_name}! Ich bin dein persönlicher CrossFit Coach.\n\n"
        f"📊 Modell: `{ud.get('llm_model')}`\n"
        f"{'🏃 Garmin: Verbunden' if garmin_email else '⚠️ Garmin: Nicht verbunden'}\n\n"
        "Schreib mir einfach – z.B. 'Bin ich heute fit genug für einen Heavy Day?'\n\n"
        "/help für alle Befehle.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Registrierung abgebrochen. Starte neu mit /start."
    )
    return ConversationHandler.END


def get_registration_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            INVITE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_invite_code)],
            CHECK_CONSENT: [CallbackQueryHandler(receive_consent, pattern="^consent_")],
            GARMIN_EMAIL: [MessageHandler(filters.TEXT, receive_garmin_email)],
            GARMIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_garmin_pass)],
            API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key)],
            LLM_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_llm_model)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
