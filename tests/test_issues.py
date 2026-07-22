"""Unit tests for the product issue service."""
from __future__ import annotations

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


def _issue(**overrides) -> dict:
    issue = {
        "id": 7,
        "user_id": 3,
        "title": "Dashboard-Link führt ins Leere",
        "body": "Klick auf den Link, dann 404.",
        "kind": "bug",
        "priority": "normal",
        "status": "open",
        "resolution": None,
        "created_at": "2026-07-20T10:00:00+00:00",
        "resolved_at": None,
        "notified_at": None,
        "users": {"full_name": "Max", "username": "max", "telegram_id": 999},
    }
    issue.update(overrides)
    return issue


# ─── create_issue ─────────────────────────────────────────────────────────────

def test_create_issue_stores_the_report(monkeypatch):
    """A reported bug lands in the table with status 'open'."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [_issue()]

    with patch("services.issues.get_db", return_value=mock_db):
        from services.issues import create_issue
        created = create_issue(3, "Dashboard-Link führt ins Leere", "404", kind="bug")

    assert created["id"] == 7
    row = mock_db.table.return_value.insert.call_args.args[0]
    assert row["status"] == "open"
    assert row["kind"] == "bug"
    assert row["user_id"] == 3


def test_create_issue_falls_back_on_unknown_kind(monkeypatch):
    """The agent may invent a kind – store 'other' rather than hit the CHECK."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [_issue()]

    with patch("services.issues.get_db", return_value=mock_db):
        from services.issues import create_issue
        create_issue(3, "Titel", kind="wunsch", priority="dringend")

    row = mock_db.table.return_value.insert.call_args.args[0]
    assert row["kind"] == "other"
    assert row["priority"] == "normal"


def test_create_issue_rejects_an_empty_title(monkeypatch):
    _mock_env(monkeypatch)
    with patch("services.issues.get_db", return_value=MagicMock()):
        from services.issues import create_issue
        with pytest.raises(ValueError):
            create_issue(3, "   ")


# ─── list_issues ──────────────────────────────────────────────────────────────

def test_list_issues_sorts_high_priority_first(monkeypatch):
    """A date-only order would bury the urgent report under newer noise."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.select.return_value.eq.return_value
    chain.order.return_value.limit.return_value.execute.return_value.data = [
        _issue(id=1, priority="low"),
        _issue(id=2, priority="high"),
        _issue(id=3, priority="normal"),
    ]

    with patch("services.issues.get_db", return_value=mock_db):
        from services.issues import list_issues
        rows = list_issues(status="open")

    assert [r["id"] for r in rows] == [2, 3, 1]


def test_list_issues_accepts_multiple_statuses(monkeypatch):
    """'open,in_progress' is the backlog view and must become an IN filter."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.select.return_value.in_.return_value
    chain.order.return_value.limit.return_value.execute.return_value.data = []

    with patch("services.issues.get_db", return_value=mock_db):
        from services.issues import list_issues
        list_issues(status="open,in_progress")

    mock_db.table.return_value.select.return_value.in_.assert_called_once_with(
        "status", ["open", "in_progress"]
    )


# ─── claim_issue ──────────────────────────────────────────────────────────────

def test_claim_issue_succeeds_while_open(monkeypatch):
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value
    chain.execute.return_value.data = [{"id": 7}]

    with patch("services.issues.get_db", return_value=mock_db), \
         patch("services.issues.get_issue", return_value=_issue(status="in_progress")):
        from services.issues import claim_issue
        claimed = claim_issue(7)

    assert claimed["status"] == "in_progress"
    assert mock_db.table.return_value.update.call_args.args[0] == {"status": "in_progress"}


def test_claim_issue_returns_none_when_already_taken(monkeypatch):
    """Two dev sessions must not silently work the same issue."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value
    chain.execute.return_value.data = []

    with patch("services.issues.get_db", return_value=mock_db):
        from services.issues import claim_issue
        assert claim_issue(7) is None


# ─── set_issue_status ─────────────────────────────────────────────────────────

def test_resolving_notifies_the_reporter(monkeypatch):
    """Closing an issue is the moment the athlete hears back."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": 7}
    ]

    with patch("services.issues.get_db", return_value=mock_db), \
         patch("services.issues.get_issue", return_value=_issue(status="in_progress")), \
         patch("utils.telegram.notify_user", return_value=True) as notify:
        from services.issues import set_issue_status
        set_issue_status(7, "done", resolution="Der Link funktioniert wieder.")

    text = notify.call_args.args[1]
    assert notify.call_args.args[0] == 999
    assert "Der Link funktioniert wieder." in text
    update = mock_db.table.return_value.update.call_args_list[0].args[0]
    assert update["status"] == "done"
    assert update["resolved_at"] is not None


def test_a_failed_notification_keeps_the_status_change(monkeypatch):
    """A Telegram outage must never roll back a resolved issue."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": 7}
    ]

    with patch("services.issues.get_db", return_value=mock_db), \
         patch("services.issues.get_issue", return_value=_issue(status="done")), \
         patch("utils.telegram.notify_user", return_value=False):
        from services.issues import set_issue_status
        result = set_issue_status(7, "done", resolution="Erledigt.")

    assert result is not None
    # notified_at is only written after a successful send
    written = [c.args[0] for c in mock_db.table.return_value.update.call_args_list]
    assert not any("notified_at" in u for u in written)


def test_reopening_clears_the_outcome_and_stays_silent(monkeypatch):
    """A fix that did not work must not leave a stale resolution behind."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": 7}
    ]

    with patch("services.issues.get_db", return_value=mock_db), \
         patch("services.issues.get_issue", return_value=_issue(status="done")), \
         patch("utils.telegram.notify_user") as notify:
        from services.issues import set_issue_status
        set_issue_status(7, "open", resolution="")

    update = mock_db.table.return_value.update.call_args.args[0]
    assert update["resolved_at"] is None
    assert update["notified_at"] is None
    notify.assert_not_called()


def test_set_issue_status_rejects_an_unknown_status(monkeypatch):
    _mock_env(monkeypatch)
    with patch("services.issues.get_db", return_value=MagicMock()):
        from services.issues import set_issue_status
        with pytest.raises(ValueError):
            set_issue_status(7, "erledigt")


# ─── Telegram rendering ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status,icon",
    [("open", "🆕"), ("in_progress", "🔧"), ("done", "✅"), ("rejected", "🚫")],
)
def test_format_issue_line_marks_every_status(monkeypatch, status, icon):
    """The athlete reads status from the icon, so none may fall back to '•'."""
    _mock_env(monkeypatch)
    from services.issues import format_issue_line
    line = format_issue_line(_issue(status=status))
    assert line.startswith(icon)
    assert "#7" in line
    assert "Bug" in line


def test_saving_the_same_outcome_twice_does_not_ping_twice(monkeypatch):
    """Hitting 'Speichern' again in the admin UI must stay silent."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": 7}
    ]
    already_done = _issue(status="done", notified_at="2026-07-21T09:00:00+00:00")

    with patch("services.issues.get_db", return_value=mock_db), \
         patch("services.issues.get_issue", return_value=already_done), \
         patch("utils.telegram.notify_user") as notify:
        from services.issues import set_issue_status
        set_issue_status(7, "done", resolution="Erledigt.")

    notify.assert_not_called()


def test_a_retry_after_a_failed_send_still_notifies(monkeypatch):
    """Same status, but never delivered – the athlete still deserves the news."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": 7}
    ]
    never_notified = _issue(status="done", notified_at=None)

    with patch("services.issues.get_db", return_value=mock_db), \
         patch("services.issues.get_issue", return_value=never_notified), \
         patch("utils.telegram.notify_user", return_value=True) as notify:
        from services.issues import set_issue_status
        set_issue_status(7, "done", resolution="Erledigt.")

    notify.assert_called_once()
