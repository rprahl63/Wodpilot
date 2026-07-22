"""The bot token must never reach the logs through httpx."""
from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def restore_levels():
    """Leave the loggers as they were – other tests share this process."""
    before = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    yield
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


def test_http_client_logs_are_silenced():
    """httpx logs the full URL, and every Bot API URL contains the token."""
    logging.getLogger("httpx").setLevel(logging.INFO)

    from utils.log import silence_http_client_logs
    silence_http_client_logs()

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
