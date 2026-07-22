"""
Telegram send helpers.

Telegram parses Markdown strictly: a single unbalanced "_" or "*" anywhere in
the text makes it reject the *entire* message with BadRequest. That bites
whenever dynamic content is interpolated — LLM answers, scraped WOD text, a
transcribed voice message, or a token from secrets.token_urlsafe(), which emits
underscores. Losing the message is worse than losing the formatting, so retry
without markup instead of letting the send fail.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def send_safe(
    send: Callable[..., Awaitable[Any]], text: str, **kwargs: Any
) -> Any:
    """Send `text` as Markdown, falling back to plain text on a parse error.

    `send` must accept the text as its first positional argument, e.g.
    `update.message.reply_text` or a partial of `bot.send_message`.
    """
    from telegram.error import BadRequest

    try:
        return await send(text, parse_mode="Markdown", **kwargs)
    except BadRequest as exc:
        if "parse entities" not in str(exc).lower():
            raise
        logger.warning("Markdown rejected by Telegram, sending as plain text: %s", exc)
        return await send(text, **kwargs)


def notify_user(telegram_id: int, text: str) -> bool:
    """Send an unsolicited message to a user over the plain Bot API.

    Used from places that have no running python-telegram-bot Application:
    the Flask admin UI and the MCP server. Deliberately without parse_mode —
    the text is free-form (an issue resolution written by a dev session), and
    a stray "_" would cost the whole message.

    Returns True when Telegram accepted the message.
    """
    import httpx

    from config import get_config

    try:
        res = httpx.post(
            f"{TELEGRAM_API}/bot{get_config().telegram_token}/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=10.0,
        )
        res.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Could not notify telegram_id %s: %s", telegram_id, exc)
        return False
