"""Unit tests for the athlete-facing dashboard blueprint (/me/...)."""
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
    monkeypatch.setenv("WEB_SECRET_KEY", "test-secret")

    import config
    config._config = None


@pytest.fixture
def client(monkeypatch):
    _mock_env(monkeypatch)
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def athlete_db():
    """Supabase mock returning a user row for _current_athlete()."""
    mock_db = MagicMock()
    chain = mock_db.table.return_value.select.return_value.eq.return_value
    chain.execute.return_value.data = [{"id": 7, "full_name": "René", "username": "rene"}]
    return mock_db


def _login(client, user_id: int = 7) -> None:
    with client.session_transaction() as sess:
        sess["athlete_user_id"] = user_id


# ─── Auth ─────────────────────────────────────────────────────────────────────

def test_week_requires_athlete_session(client):
    """Without a session the week view returns the login error page."""
    res = client.get("/me/")
    assert res.status_code == 401
    assert "Link ungültig" in res.get_data(as_text=True)


def test_auth_sets_session_for_valid_token(client):
    """A valid magic link logs the athlete in and redirects to the week view."""
    with patch("services.login_tokens.consume_login_token", return_value=7):
        res = client.get("/me/auth/good-token")

    assert res.status_code == 302
    assert res.headers["Location"].endswith("/me/")
    with client.session_transaction() as sess:
        assert sess["athlete_user_id"] == 7


def test_auth_rejects_invalid_token(client):
    """An invalid token must not create a session."""
    with patch("services.login_tokens.consume_login_token", return_value=None):
        res = client.get("/me/auth/bad-token")

    assert res.status_code == 401
    with client.session_transaction() as sess:
        assert "athlete_user_id" not in sess


def test_logout_keeps_admin_session(client):
    """Logging out of the athlete area leaves an admin session intact."""
    with client.session_transaction() as sess:
        sess["athlete_user_id"] = 7
        sess["logged_in"] = True

    client.get("/me/logout")

    with client.session_transaction() as sess:
        assert "athlete_user_id" not in sess
        assert sess["logged_in"] is True


# ─── Admin "view as athlete" ─────────────────────────────────────────────────

def test_view_as_athlete_requires_admin_login(client):
    """Without an admin session this must not hand out an athlete session."""
    res = client.get("/users/7/dashboard")

    assert res.status_code == 302
    assert "/login" in res.headers["Location"]
    with client.session_transaction() as sess:
        assert "athlete_user_id" not in sess


def test_view_as_athlete_sets_session_for_admin(client, athlete_db):
    """An admin can open any athlete's dashboard from the user page."""
    with client.session_transaction() as sess:
        sess["logged_in"] = True

    with patch("web.app.get_db", return_value=athlete_db):
        res = client.get("/users/7/dashboard")

    assert res.status_code == 302
    assert res.headers["Location"].endswith("/me/")
    with client.session_transaction() as sess:
        assert sess["athlete_user_id"] == 7
        assert sess["logged_in"] is True  # admin session survives


def test_view_as_athlete_404_for_unknown_user(client):
    """A user id that does not exist must not create a session."""
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

    with client.session_transaction() as sess:
        sess["logged_in"] = True

    with patch("web.app.get_db", return_value=mock_db):
        res = client.get("/users/999/dashboard")

    assert res.status_code == 404
    with client.session_transaction() as sess:
        assert "athlete_user_id" not in sess


# ─── Week view ────────────────────────────────────────────────────────────────

def test_week_renders_all_seven_days(client, athlete_db):
    """The week view always shows Monday–Sunday, even without a plan."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.get_week_plan", return_value=None):
        res = client.get("/me/?week=2026-07-20")

    body = res.get_data(as_text=True)
    assert res.status_code == 200
    for day in ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]:
        assert day in body
    assert "Noch kein Plan für diese Woche" in body


def test_week_renders_sessions_with_result_form(client, athlete_db):
    """Planned sessions show their description and a result form."""
    _login(client)
    plan = {
        "id": 11,
        "status": "planned",
        "constraints_text": None,
        "sessions": [
            {
                "id": 101, "date": "2026-07-20", "position": 0,
                "title": "Intervalle 6x400m", "session_type": "intervals",
                "description": "Warm-Up 15min\n6x400m @ 5k-Pace, 90s Pause",
                "status": "planned", "result_text": None, "rpe": None, "result_notes": None,
            }
        ],
    }
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.get_week_plan", return_value=plan):
        res = client.get("/me/?week=2026-07-20")

    body = res.get_data(as_text=True)
    assert "Intervalle 6x400m" in body
    assert "6x400m @ 5k-Pace, 90s Pause" in body
    assert 'action="/me/sessions/101/result"' in body
    assert "Ergebnis eintragen" in body


def test_week_falls_back_to_current_week_on_bad_param(client, athlete_db):
    """A malformed ?week param must not 500 the page."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.get_week_plan", return_value=None) as mock_plan:
        res = client.get("/me/?week=not-a-date")

    assert res.status_code == 200
    from services.planning import current_week_start
    assert mock_plan.call_args.args[1] == current_week_start()


def test_week_param_is_normalised_to_monday(client, athlete_db):
    """Any date in a week resolves to that week's Monday."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.get_week_plan", return_value=None) as mock_plan:
        client.get("/me/?week=2026-07-23")  # a Thursday

    assert mock_plan.call_args.args[1] == date(2026, 7, 20)


# ─── Result entry ─────────────────────────────────────────────────────────────

def test_session_result_saves_and_redirects(client, athlete_db):
    """A valid result form stores the result scoped to the logged-in athlete."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.log_session_result",
               return_value={"id": 101, "title": "Intervalle", "date": "2026-07-20"}) as mock_log:
        res = client.post(
            "/me/sessions/101/result",
            data={"status": "done", "result_text": "6x400 avg 1:31", "rpe": "8",
                  "result_notes": "hart", "week": "2026-07-20"},
        )

    assert res.status_code == 302
    assert mock_log.call_args.args == (7,)
    kwargs = mock_log.call_args.kwargs
    assert kwargs["session_id"] == 101
    assert kwargs["status"] == "done"
    assert kwargs["result_text"] == "6x400 avg 1:31"
    assert kwargs["rpe"] == 8


def test_session_result_rejects_foreign_session(client, athlete_db):
    """A session belonging to someone else is not found and returns 404."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.log_session_result", return_value=None):
        res = client.post("/me/sessions/999/result", data={"status": "done"})

    assert res.status_code == 404


def test_session_result_rejects_out_of_range_rpe(client, athlete_db):
    """RPE outside 1-10 is refused before touching the database."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.log_session_result") as mock_log:
        res = client.post(
            "/me/sessions/101/result",
            data={"status": "done", "rpe": "42", "week": "2026-07-20"},
        )

    assert res.status_code == 302
    mock_log.assert_not_called()


def test_session_result_requires_session(client):
    """Posting a result without being logged in is refused."""
    res = client.post("/me/sessions/101/result", data={"status": "done"})
    assert res.status_code == 401


# ─── Preferences ──────────────────────────────────────────────────────────────

def test_preferences_shows_stored_text(client, athlete_db):
    """The preferences form is prefilled with the stored text."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.get_preferences", return_value="2x Laufen pro Woche"):
        res = client.get("/me/preferences")

    assert res.status_code == 200
    assert "2x Laufen pro Woche" in res.get_data(as_text=True)


def test_preferences_post_saves_text(client, athlete_db):
    """Submitting the form stores the text for the logged-in athlete."""
    _login(client)
    with patch("db.client.get_db", return_value=athlete_db), \
         patch("services.planning.save_preferences") as mock_save:
        res = client.post(
            "/me/preferences",
            data={"preferences_text": "1x Intervalle, 2x Laufen, 2x Box  "},
        )

    assert res.status_code == 302
    mock_save.assert_called_once_with(7, "1x Intervalle, 2x Laufen, 2x Box")
