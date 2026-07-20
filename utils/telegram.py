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
