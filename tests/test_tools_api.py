"""Unit tests for the Flask /api/tools/* routes (called by pi-agent service)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet


def _mock_env(monkeypatch, token: str = "test-token") -> None:
    """Set required env vars and reset config singleton."""
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("SUPABASE_URL", "https://dummy.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "dummy")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INTERNAL_API_TOKEN", token)

    import config
    config._config = None


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(monkeypatch):
    """Return a Flask test client. Service functions are mocked per test."""
    _mock_env(monkeypatch)
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ─── Auth ─────────────────────────────────────────────────────────────────────

def test_tools_api_rejects_without_token(client):
    """Tools API should return 401 when no Authorization header is present."""
    res = client.get("/api/tools/wods")
    assert res.status_code == 401


def test_tools_api_rejects_with_wrong_token(client):
    """Tools API should return 401 when the token is wrong."""
    res = client.get(
        "/api/tools/wods", headers={"Authorization": "Bearer wrong"}
    )
    assert res.status_code == 401


def test_tools_api_disabled_when_token_empty(monkeypatch):
    """When INTERNAL_API_TOKEN is empty, requests pass without auth."""
    _mock_env(monkeypatch, token="")
    with patch("services.scraper.get_todays_wods", return_value=[]):
        from web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        res = client.get("/api/tools/wods")  # no auth header
    assert res.status_code == 200


# ─── /api/tools/training-load ────────────────────────────────────────────────

def test_training_load_returns_metrics(client, auth_headers):
    """Training load endpoint should return ATL/CTL/TSB JSON."""
    fake_load = MagicMock(
        atl=55.0, ctl=70.0, tsb=15.0,
        weekly_tss=350, run_km_14d=12.5,
        recommendation="Frisch – ruhig drauf",
    )
    with patch("services.garmin.get_training_load", return_value=fake_load):
        res = client.get("/api/tools/training-load?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    data = res.get_json()
    assert data["atl"] == 55.0
    assert data["ctl"] == 70.0
    assert data["tsb"] == 15.0
    assert data["recommendation"] == "Frisch – ruhig drauf"


def test_training_load_requires_user_id(client, auth_headers):
    """Missing user_id should return 400."""
    res = client.get("/api/tools/training-load", headers=auth_headers)
    assert res.status_code == 400
    assert "user_id required" in res.get_json()["error"]


# ─── /api/tools/wods ─────────────────────────────────────────────────────────

def test_wods_returns_list(client, auth_headers):
    """WODs endpoint should return scraped WOD list."""
    wods = [
        {"source": "BoxA", "content": "5 RFT: 10 Pull-ups, 20 Push-ups"},
        {"source": "BoxB", "content": "AMRAP 20: 5 Cleans, 10 Box Jumps"},
    ]
    with patch("services.scraper.get_todays_wods", return_value=wods):
        res = client.get("/api/tools/wods", headers=auth_headers)

    assert res.status_code == 200
    assert res.get_json() == wods


def test_wods_returns_message_when_empty(client, auth_headers):
    """No WODs should return a friendly message instead of an empty list."""
    with patch("services.scraper.get_todays_wods", return_value=[]):
        res = client.get("/api/tools/wods", headers=auth_headers)

    assert res.status_code == 200
    assert "Keine WODs" in res.get_json()["message"]


# ─── /api/tools/save-memory (POST) ───────────────────────────────────────────

def test_save_memory_posts_to_service(client, auth_headers):
    """save-memory should call save_memory(user_id, key, value, category)."""
    with patch("memory.semantic.save_memory") as mock_save:
        res = client.post(
            "/api/tools/save-memory",
            json={
                "user_id": 1,
                "key": "shoulder_injury",
                "value": "Right shoulder, June 2024",
                "category": "injury",
            },
            headers=auth_headers,
        )

    assert res.status_code == 200
    mock_save.assert_called_once_with(
        1, "shoulder_injury", "Right shoulder, June 2024", "injury"
    )


def test_save_memory_validates_required_fields(client, auth_headers):
    """Missing user_id or key should return 400."""
    res = client.post(
        "/api/tools/save-memory",
        json={"user_id": 1},  # missing key
        headers=auth_headers,
    )
    assert res.status_code == 400


# ─── /api/tools/prs ──────────────────────────────────────────────────────────

def test_prs_returns_list(client, auth_headers):
    """PRs endpoint should return episodic PRs."""
    prs = [
        {"content": "Deadlift 180kg", "category": "pr"},
        {"content": "Fran 3:42", "category": "pr"},
    ]
    with patch("memory.episodic.get_prs", return_value=prs):
        res = client.get("/api/tools/prs?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    assert res.get_json() == prs


def test_prs_message_when_empty(client, auth_headers):
    """No PRs should return a friendly message."""
    with patch("memory.episodic.get_prs", return_value=[]):
        res = client.get("/api/tools/prs?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    assert "Noch keine PRs" in res.get_json()["message"]


# ─── /api/tools/coaching-profile ─────────────────────────────────────────────

def test_coaching_profile_returns_dict(client, auth_headers):
    """Coaching profile should return profile dict."""
    profile = {"coaching_style": "direct", "notes": "no fluff"}
    with patch("memory.procedural.get_coaching_profile", return_value=profile):
        res = client.get(
            "/api/tools/coaching-profile?user_id=1", headers=auth_headers
        )

    assert res.status_code == 200
    assert res.get_json() == profile


# ─── /api/tools/training-preferences ─────────────────────────────────────────

def test_training_preferences_requires_token(client):
    """Preferences endpoint is internal-only."""
    assert client.get("/api/tools/training-preferences?user_id=1").status_code == 401


def test_training_preferences_returns_text(client, auth_headers):
    """GET returns the stored preferences."""
    with patch("services.planning.get_preferences", return_value="2x Laufen"):
        res = client.get("/api/tools/training-preferences?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    assert res.get_json()["preferences_text"] == "2x Laufen"


def test_training_preferences_message_when_empty(client, auth_headers):
    """No preferences yields a friendly message, not an empty string."""
    with patch("services.planning.get_preferences", return_value=""):
        res = client.get("/api/tools/training-preferences?user_id=1", headers=auth_headers)

    assert "Noch keine Präferenzen" in res.get_json()["message"]


def test_training_preferences_post_saves(client, auth_headers):
    """POST stores the new preferences text."""
    with patch("services.planning.save_preferences") as mock_save:
        res = client.post(
            "/api/tools/training-preferences",
            json={"user_id": 1, "preferences_text": "1x Intervalle, 2x Laufen"},
            headers=auth_headers,
        )

    assert res.status_code == 200
    mock_save.assert_called_once_with(1, "1x Intervalle, 2x Laufen")


def test_training_preferences_post_rejects_empty_text(client, auth_headers):
    """An empty preferences text is a client error."""
    res = client.post(
        "/api/tools/training-preferences",
        json={"user_id": 1, "preferences_text": "  "},
        headers=auth_headers,
    )
    assert res.status_code == 400


# ─── /api/tools/week-plan ────────────────────────────────────────────────────

def test_week_plan_requires_token(client):
    """Week plan endpoint is internal-only."""
    assert client.get("/api/tools/week-plan?user_id=1").status_code == 401


def test_week_plan_returns_plan_with_sessions(client, auth_headers):
    """GET returns the plan including session ids the agent needs for logging."""
    plan = {"id": 11, "status": "planned", "sessions": [{"id": 101, "title": "Fran"}]}
    with patch("services.planning.get_week_plan", return_value=plan):
        res = client.get(
            "/api/tools/week-plan?user_id=1&week_start=2026-07-20", headers=auth_headers
        )

    assert res.status_code == 200
    assert res.get_json()["sessions"][0]["id"] == 101


def test_week_plan_defaults_to_current_week(client, auth_headers):
    """Without week_start the current week is used."""
    with patch("services.planning.get_week_plan", return_value=None) as mock_get:
        res = client.get("/api/tools/week-plan?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    from services.planning import current_week_start
    assert mock_get.call_args.args[1] == current_week_start().isoformat()


def test_week_plan_post_saves_sessions(client, auth_headers):
    """POST hands the sessions to save_week_plan."""
    sessions = [
        {"date": "2026-07-20", "title": "Intervalle", "description": "6x400m"},
    ]
    with patch("services.planning.save_week_plan", return_value=1) as mock_save:
        res = client.post(
            "/api/tools/week-plan",
            json={"user_id": 1, "week_start": "2026-07-20", "sessions": sessions},
            headers=auth_headers,
        )

    assert res.status_code == 200
    mock_save.assert_called_once_with(1, "2026-07-20", sessions)
    assert "1 Einheiten" in res.get_json()["message"]


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": 1, "sessions": [{"date": "d", "title": "t", "description": "x"}]},
        {"user_id": 1, "week_start": "2026-07-20", "sessions": []},
        {"user_id": 1, "week_start": "2026-07-20", "sessions": "nope"},
        {"user_id": 1, "week_start": "2026-07-20", "sessions": [{"title": "no date"}]},
    ],
    ids=["missing_week_start", "empty_sessions", "sessions_not_a_list", "session_missing_fields"],
)
def test_week_plan_post_validates_payload(client, auth_headers, payload):
    """Malformed plans are rejected before anything is written."""
    with patch("services.planning.save_week_plan") as mock_save:
        res = client.post("/api/tools/week-plan", json=payload, headers=auth_headers)

    assert res.status_code == 400
    mock_save.assert_not_called()


# ─── /api/tools/session-result ───────────────────────────────────────────────

def test_session_result_requires_token(client):
    """Result endpoint is internal-only."""
    assert client.post("/api/tools/session-result", json={}).status_code == 401


def test_session_result_logs_result(client, auth_headers):
    """A well-formed result is passed through to the planning service."""
    stored = {"id": 101, "title": "Intervalle", "date": "2026-07-20"}
    with patch("services.planning.log_session_result", return_value=stored) as mock_log:
        res = client.post(
            "/api/tools/session-result",
            json={"user_id": 1, "session_id": 101, "status": "done",
                  "result_text": "6x400 avg 1:31", "rpe": 9},
            headers=auth_headers,
        )

    assert res.status_code == 200
    assert "Intervalle" in res.get_json()["message"]
    kwargs = mock_log.call_args.kwargs
    assert kwargs["session_id"] == 101
    assert kwargs["rpe"] == 9


def test_session_result_message_when_no_match(client, auth_headers):
    """An unmatched session tells the agent how to recover."""
    with patch("services.planning.log_session_result", return_value=None):
        res = client.post(
            "/api/tools/session-result",
            json={"user_id": 1, "session_id": 999, "status": "done"},
            headers=auth_headers,
        )

    assert res.status_code == 200
    assert "get_week_plan" in res.get_json()["message"]


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": 1},
        {"user_id": 1, "session_id": 1, "status": "vielleicht"},
        {"user_id": 1, "session_id": 1, "rpe": 11},
        {"user_id": 1, "session_id": 1, "rpe": "acht"},
    ],
    ids=["no_id_or_date", "bad_status", "rpe_too_high", "rpe_not_a_number"],
)
def test_session_result_validates_payload(client, auth_headers, payload):
    """Bad results are rejected before touching the database."""
    with patch("services.planning.log_session_result") as mock_log:
        res = client.post("/api/tools/session-result", json=payload, headers=auth_headers)

    assert res.status_code == 400
    mock_log.assert_not_called()


# ─── Issues ───────────────────────────────────────────────────────────────────

def test_issues_endpoint_requires_token(client):
    """The issue endpoint is internal like every other tools route."""
    res = client.post("/api/tools/issues", json={"user_id": 1, "title": "x"})
    assert res.status_code == 401


def test_create_issue_stores_the_report(client, auth_headers):
    """A filed bug comes back with its number so the coach can name it."""
    created = {"id": 12, "title": "Dashboard-Link tot"}
    with patch("services.issues.create_issue", return_value=created) as mock_create:
        res = client.post(
            "/api/tools/issues",
            json={"user_id": 1, "title": "Dashboard-Link tot",
                  "body": "404 nach Klick", "kind": "bug", "priority": "high"},
            headers=auth_headers,
        )

    assert res.status_code == 200
    assert res.get_json()["issue_id"] == 12
    assert "#12" in res.get_json()["message"]
    kwargs = mock_create.call_args.kwargs
    assert kwargs["kind"] == "bug"
    assert kwargs["priority"] == "high"


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": 1},
        {"title": "Kein Nutzer"},
        {"user_id": 1, "title": "x", "kind": "wunsch"},
        {"user_id": 1, "title": "x", "priority": "sofort"},
    ],
    ids=["no_title", "no_user", "bad_kind", "bad_priority"],
)
def test_create_issue_validates_payload(client, auth_headers, payload):
    """Invalid input is rejected before it can hit the CHECK constraint."""
    with patch("services.issues.create_issue") as mock_create:
        res = client.post("/api/tools/issues", json=payload, headers=auth_headers)

    assert res.status_code == 400
    mock_create.assert_not_called()


def test_list_issues_returns_only_the_athletes_own(client, auth_headers):
    """The coach must never surface another athlete's report."""
    rows = [{
        "id": 12, "title": "Dashboard-Link tot", "kind": "bug", "priority": "high",
        "status": "open", "created_at": "2026-07-20T10:00:00+00:00", "body": "geheim",
    }]
    with patch("services.issues.list_issues", return_value=rows) as mock_list:
        res = client.get("/api/tools/issues?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    assert mock_list.call_args.kwargs["user_id"] == 1
    assert res.get_json()[0]["id"] == 12


def test_list_issues_message_when_none(client, auth_headers):
    """An empty backlog reads as a sentence, not as an empty list."""
    with patch("services.issues.list_issues", return_value=[]):
        res = client.get("/api/tools/issues?user_id=1", headers=auth_headers)

    assert res.status_code == 200
    assert "Keine offenen Issues" in res.get_json()["message"]
