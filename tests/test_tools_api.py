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
