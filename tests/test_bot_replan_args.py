"""Unit tests for /replan argument parsing."""
from __future__ import annotations

from datetime import date

import pytest
from cryptography.fernet import Fernet


def _mock_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("SUPABASE_URL", "https://dummy.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "dummy")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

    import config
    config._config = None


@pytest.fixture(autouse=True)
def env(monkeypatch):
    _mock_env(monkeypatch)


def test_no_args_plans_the_current_week():
    """Mid-week you want to fix the week you are in, not the next one."""
    from bot.handlers import parse_replan_args
    from services.planning import current_week_start

    week, constraints = parse_replan_args([])
    assert week == current_week_start()
    assert constraints is None


def test_bare_constraints_keep_the_current_week():
    """Free text alone must not be mistaken for a week selector."""
    from bot.handlers import parse_replan_args
    from services.planning import current_week_start

    week, constraints = parse_replan_args(["Mittwoch", "keine", "Zeit"])
    assert week == current_week_start()
    assert constraints == "Mittwoch keine Zeit"


@pytest.mark.parametrize("word", ["next", "nächste", "naechste", "kommende", "NEXT"])
def test_next_selects_the_upcoming_week(word):
    """A leading 'next' switches to the coming week."""
    from bot.handlers import parse_replan_args
    from services.planning import upcoming_week_start

    week, constraints = parse_replan_args([word, "Samstag", "Wettkampf"])
    assert week == upcoming_week_start()
    assert constraints == "Samstag Wettkampf"


def test_iso_date_selects_that_week_normalised_to_monday():
    """An explicit date picks its week, whatever weekday it names."""
    from bot.handlers import parse_replan_args

    week, constraints = parse_replan_args(["2026-07-23", "Urlaub"])
    assert week == date(2026, 7, 20)  # Thursday → that Monday
    assert constraints == "Urlaub"


def test_selector_without_constraints_yields_none():
    """Only a week selector means no constraints for the planner."""
    from bot.handlers import parse_replan_args
    from services.planning import upcoming_week_start

    week, constraints = parse_replan_args(["next"])
    assert week == upcoming_week_start()
    assert constraints is None


def test_unparseable_leading_token_stays_in_constraints():
    """A date-looking but invalid token must not be swallowed silently."""
    from bot.handlers import parse_replan_args
    from services.planning import current_week_start

    week, constraints = parse_replan_args(["2026-13-99", "kaputt"])
    assert week == current_week_start()
    assert constraints == "2026-13-99 kaputt"
