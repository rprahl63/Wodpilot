"""Logging setup shared by every entry point."""
from __future__ import annotations

import logging


def silence_http_client_logs() -> None:
    """Stop httpx from logging request URLs at INFO level.

    Every Telegram Bot API call carries the bot token in its path
    (`/bot<TOKEN>/sendMessage`), and httpx logs the full URL by default. The
    bot polls getUpdates every few seconds, so the token ends up repeated
    thousands of times a day in `docker logs` — and from there in every log
    backup. The MCP server and the web app hit the same API through
    `utils.telegram.notify_user`.

    The tradeoff is losing the per-request HTTP line. That is acceptable here:
    failures surface as exceptions that the calling code logs itself. Drop the
    level back to INFO temporarily when debugging a transport problem.
    """
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
