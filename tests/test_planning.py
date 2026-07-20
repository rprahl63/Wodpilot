"""Unit tests for the weekly planning service."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

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


# ─── Date helpers (pure functions, no DB) ────────────────────────────────────

@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 7, 20), date(2026, 7, 20)),  # Monday → itself
        (date(2026, 7, 24), date(2026, 7, 20)),  # Friday → that Monday
        (date(2026, 7, 26), date(2026, 7, 20)),  # Sunday → the Monday before
    ],
)
def test_current_week_start(today, expected):
    """current_week_start returns the Monday of the week containing today."""
    from services.planning import current_week_start
    assert current_week_start(today) == expected


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 7, 20), date(2026, 7, 27)),  # Monday → next Monday
        (date(2026, 7, 24), date(2026, 7, 27)),  # Friday → next Monday
        (date(2026, 7, 26), date(2026, 7, 27)),  # Sunday → tomorrow
    ],
)
def test_upcoming_week_start(today, expected):
    """upcoming_week_start always returns the Monday strictly after today."""
    from services.planning import upcoming_week_start
    assert upcoming_week_start(today) == expected


def test_upcoming_week_start_is_always_a_monday_in_the_future():
    """The Sunday edge case must not return today's date."""
    from services.planning import upcoming_week_start
    for offset in range(14):
        today = date(2026, 7, 20) + __import__("datetime").timedelta(days=offset)
        result = upcoming_week_start(today)
        assert result.weekday() == 0
        assert result > today


# ─── claim_planning ───────────────────────────────────────────────────────────

def test_claim_planning_succeeds_when_row_still_asked(monkeypatch):
    """A conditional update that touched a row means the claim succeeded."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value
    chain.execute.return_value.data = [{"id": 5, "status": "planning"}]

    with patch("services.planning.get_db", return_value=mock_db):
        from services.planning import claim_planning
        assert claim_planning(5, "Mittwoch keine Zeit") is True

    update_arg = mock_db.table.return_value.update.call_args.args[0]
    assert update_arg["status"] == "planning"
    assert update_arg["constraints_text"] == "Mittwoch keine Zeit"


def test_claim_planning_fails_when_already_claimed(monkeypatch):
    """No affected row means another caller already claimed the week."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value
    chain.execute.return_value.data = []

    with patch("services.planning.get_db", return_value=mock_db):
        from services.planning import claim_planning
        assert claim_planning(5) is False


def test_claim_planning_without_constraints_keeps_existing_text(monkeypatch):
    """The fallback job claims without a reply and must not null the text."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value
    chain.execute.return_value.data = [{"id": 5}]

    with patch("services.planning.get_db", return_value=mock_db):
        from services.planning import claim_planning
        claim_planning(5)

    assert "constraints_text" not in mock_db.table.return_value.update.call_args.args[0]


# ─── claim_replan ─────────────────────────────────────────────────────────────

def test_claim_replan_overwrites_an_already_planned_week(monkeypatch):
    """Re-planning a finished week is the whole point of /replan."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.neq.return_value
    chain.execute.return_value.data = [{"id": 11, "status": "planning"}]

    with patch("services.planning.get_db", return_value=mock_db), \
         patch("services.planning.get_week_plan",
               return_value={"id": 11, "status": "planned"}):
        from services.planning import claim_replan
        plan = claim_replan(3, "2026-07-20", "Donnerstag Physio")

    assert plan["id"] == 11
    update_arg = mock_db.table.return_value.update.call_args.args[0]
    assert update_arg["status"] == "planning"
    assert update_arg["constraints_text"] == "Donnerstag Physio"


def test_claim_replan_refuses_while_planning_in_flight(monkeypatch):
    """Two /replan calls in a row must not plan the same week twice."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.neq.return_value
    chain.execute.return_value.data = []

    with patch("services.planning.get_db", return_value=mock_db), \
         patch("services.planning.get_week_plan",
               return_value={"id": 11, "status": "planning"}):
        from services.planning import claim_replan
        assert claim_replan(3, "2026-07-20") is None


def test_claim_replan_creates_row_for_unplanned_week(monkeypatch):
    """A week nobody asked about yet gets a fresh plan row."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": 99}]

    with patch("services.planning.get_db", return_value=mock_db), \
         patch("services.planning.get_week_plan", return_value=None):
        from services.planning import claim_replan
        plan = claim_replan(3, "2026-07-20", "kurze Woche")

    assert plan["id"] == 99
    inserted = mock_db.table.return_value.insert.call_args.args[0]
    assert inserted["user_id"] == 3
    assert inserted["week_start"] == "2026-07-20"
    assert inserted["status"] == "planning"
    assert inserted["constraints_text"] == "kurze Woche"


# ─── save_week_plan ───────────────────────────────────────────────────────────

def test_save_week_plan_replaces_sessions_and_marks_planned(monkeypatch):
    """Existing sessions are deleted before the new ones are inserted."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()

    sessions = [
        {"date": "2026-07-27", "title": "Intervalle", "session_type": "intervals",
         "description": "6x400m @ 5k-Pace"},
        {"date": "2026-07-29", "title": "Longrun", "description": "60min locker"},
    ]

    with patch("services.planning.get_db", return_value=mock_db), \
         patch("services.planning.get_week_plan", return_value={"id": 11, "status": "planning"}):
        from services.planning import save_week_plan
        count = save_week_plan(3, "2026-07-27", sessions)

    assert count == 2
    mock_db.table.return_value.delete.return_value.eq.assert_called_with("plan_id", 11)

    inserted = mock_db.table.return_value.insert.call_args.args[0]
    assert len(inserted) == 2
    assert inserted[0]["plan_id"] == 11
    assert inserted[0]["user_id"] == 3
    assert inserted[0]["position"] == 0
    assert inserted[1]["position"] == 1
    assert inserted[1]["session_type"] is None

    status_update = mock_db.table.return_value.update.call_args.args[0]
    assert status_update["status"] == "planned"
    assert status_update["planned_at"]


def test_save_week_plan_creates_plan_row_when_missing(monkeypatch):
    """/replan without a Sunday ask must still get a plan row."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": 99}]

    with patch("services.planning.get_db", return_value=mock_db), \
         patch("services.planning.get_week_plan", return_value=None):
        from services.planning import save_week_plan
        count = save_week_plan(3, "2026-07-27", [
            {"date": "2026-07-27", "title": "WOD", "description": "Fran"}
        ])

    assert count == 1
    first_insert = mock_db.table.return_value.insert.call_args_list[0].args[0]
    assert first_insert["user_id"] == 3
    assert first_insert["week_start"] == "2026-07-27"


# ─── log_session_result ───────────────────────────────────────────────────────

def _mock_db_for_lookup(found_id: int | None):
    """Supabase mock whose select chain yields one session id (or none)."""
    mock_db = MagicMock()
    select_chain = mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value
    select_chain.order.return_value.limit.return_value.execute.return_value.data = (
        [{"id": found_id}] if found_id else []
    )
    update_chain = mock_db.table.return_value.update.return_value.eq.return_value
    update_chain.execute.return_value.data = [
        {"id": found_id, "title": "Intervalle", "date": "2026-07-27"}
    ]
    return mock_db


def test_log_session_result_filters_by_user_id(monkeypatch):
    """The lookup must always be scoped to the user – no cross-user writes."""
    _mock_env(monkeypatch)
    mock_db = _mock_db_for_lookup(42)

    with patch("services.planning.get_db", return_value=mock_db):
        from services.planning import log_session_result
        result = log_session_result(7, session_id=42, status="done", result_text="1:31", rpe=9)

    assert result["id"] == 42
    eq_calls = mock_db.table.return_value.select.return_value.eq.call_args_list
    assert eq_calls[0].args == ("user_id", 7)

    update_arg = mock_db.table.return_value.update.call_args.args[0]
    assert update_arg["status"] == "done"
    assert update_arg["result_text"] == "1:31"
    assert update_arg["rpe"] == 9
    assert update_arg["completed_at"]


def test_log_session_result_returns_none_for_foreign_session(monkeypatch):
    """A session id belonging to another user finds nothing and writes nothing."""
    _mock_env(monkeypatch)
    mock_db = _mock_db_for_lookup(None)

    with patch("services.planning.get_db", return_value=mock_db):
        from services.planning import log_session_result
        assert log_session_result(7, session_id=999) is None

    mock_db.table.return_value.update.assert_not_called()


def test_log_session_result_requires_id_or_date(monkeypatch):
    """Neither id nor date given is a programming error."""
    _mock_env(monkeypatch)
    with patch("services.planning.get_db", return_value=MagicMock()):
        from services.planning import log_session_result
        with pytest.raises(ValueError, match="session_id oder session_date"):
            log_session_result(7)


def test_log_session_result_rejects_unknown_status(monkeypatch):
    """Only the three known statuses are accepted."""
    _mock_env(monkeypatch)
    with patch("services.planning.get_db", return_value=MagicMock()):
        from services.planning import log_session_result
        with pytest.raises(ValueError, match="Ungültiger Status"):
            log_session_result(7, session_id=1, status="halbwegs")
