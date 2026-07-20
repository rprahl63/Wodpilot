"""Unit tests for the Markdown-safe Telegram send helper."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from utils.telegram import send_safe


def test_sends_with_markdown_when_it_parses():
    """The happy path keeps the formatting."""
    send = AsyncMock(return_value="ok")

    result = asyncio.run(send_safe(send, "*fett*"))

    assert result == "ok"
    send.assert_awaited_once_with("*fett*", parse_mode="Markdown")


def test_falls_back_to_plain_text_on_parse_error():
    """An unbalanced underscore must not cost the whole message."""
    send = AsyncMock(
        side_effect=[
            BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 66"),
            "ok",
        ]
    )

    # A real token_urlsafe() value with a single underscore – exactly what broke
    # /dashboard on roughly every other call.
    text = "http://host:8080/me/auth/xY_abc-DEF"
    result = asyncio.run(send_safe(send, text))

    assert result == "ok"
    assert send.await_count == 2
    assert send.await_args_list[0].kwargs["parse_mode"] == "Markdown"
    assert "parse_mode" not in send.await_args_list[1].kwargs


def test_passes_through_extra_kwargs():
    """Caller kwargs survive both attempts."""
    send = AsyncMock(side_effect=[BadRequest("can't parse entities"), "ok"])

    asyncio.run(send_safe(send, "_kaputt", disable_web_page_preview=True))

    for call in send.await_args_list:
        assert call.kwargs["disable_web_page_preview"] is True


def test_unrelated_badrequest_is_reraised():
    """Only parse errors are retried – a real failure must stay visible."""
    send = AsyncMock(side_effect=BadRequest("chat not found"))

    with pytest.raises(BadRequest, match="chat not found"):
        asyncio.run(send_safe(send, "hallo"))

    send.assert_awaited_once()
