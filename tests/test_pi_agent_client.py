"""Unit tests for the pi-agent HTTP client."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet


def _mock_env(monkeypatch) -> str:
    """Set required env vars; return the encryption key used."""
    enc_key = Fernet.generate_key().decode()
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("SUPABASE_URL", "https://dummy.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "dummy")
    monkeypatch.setenv("ENCRYPTION_KEY", enc_key)
    monkeypatch.setenv("PI_AGENT_URL", "http://test-pi-agent:3001")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token")

    import config
    config._config = None
    return enc_key


def _mock_db_with_user(api_key_enc: str | None, calls_today: int = 0, reset_today: bool = True):
    """Build a Supabase mock that returns a user row with the given fields."""
    from datetime import date
    today = date.today().isoformat() if reset_today else "2000-01-01"

    user_row = {
        "llm_api_key_enc": api_key_enc,
        "llm_model": "claude-sonnet-4-20250514",
        "api_calls_today": calls_today,
        "api_calls_reset_at": today,
    }

    mock_db = MagicMock()
    chain = mock_db.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = user_row
    # update().eq().execute() chain – just don't break
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return mock_db


def _build_async_httpx_mock(json_response: dict):
    """Mock httpx.AsyncClient whose .post() returns the given JSON."""
    mock_response = MagicMock()
    mock_response.json.return_value = json_response
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client, mock_response


# ─── _get_user_api_key ───────────────────────────────────────────────────────

def test_get_user_api_key_raises_without_key(monkeypatch):
    """Should raise ValueError when no api key is stored."""
    _mock_env(monkeypatch)
    mock_db = _mock_db_with_user(api_key_enc=None)

    with patch("services.pi_agent_client.get_db", return_value=mock_db):
        from services.pi_agent_client import _get_user_api_key
        with pytest.raises(ValueError, match="Kein API-Key hinterlegt"):
            _get_user_api_key(1)


def test_get_user_api_key_decrypts_and_returns_model(monkeypatch):
    """Should decrypt the stored key and return (key, model)."""
    _mock_env(monkeypatch)

    from utils.crypto import encrypt
    encrypted = encrypt("sk-ant-secret-key")
    mock_db = _mock_db_with_user(api_key_enc=encrypted)

    with patch("services.pi_agent_client.get_db", return_value=mock_db):
        from services.pi_agent_client import _get_user_api_key
        api_key, model = _get_user_api_key(1)

    assert api_key == "sk-ant-secret-key"
    assert model == "claude-sonnet-4-20250514"


# ─── _check_and_increment_rate_limit ─────────────────────────────────────────

def test_rate_limit_resets_on_new_day(monkeypatch):
    """A reset_at older than today should reset the counter to 1."""
    _mock_env(monkeypatch)
    mock_db = _mock_db_with_user(
        api_key_enc="ignored", calls_today=999, reset_today=False
    )

    with patch("services.pi_agent_client.get_db", return_value=mock_db):
        from services.pi_agent_client import _check_and_increment_rate_limit
        _check_and_increment_rate_limit(1)  # should not raise

    # Verify the update call was made (reset to 1)
    update_calls = mock_db.table.return_value.update.call_args_list
    assert any(
        call.args[0].get("api_calls_today") == 1 for call in update_calls
    ), "Expected reset to api_calls_today=1"


def test_rate_limit_raises_at_max(monkeypatch):
    """Should raise when calls_today >= max_api_calls_per_day."""
    _mock_env(monkeypatch)
    monkeypatch.setenv("MAX_API_CALLS_PER_DAY", "5")

    import config
    config._config = None

    mock_db = _mock_db_with_user(
        api_key_enc="ignored", calls_today=5, reset_today=True
    )

    with patch("services.pi_agent_client.get_db", return_value=mock_db):
        from services.pi_agent_client import _check_and_increment_rate_limit
        with pytest.raises(ValueError, match="Tägliches Limit"):
            _check_and_increment_rate_limit(1)


# ─── _build_history ──────────────────────────────────────────────────────────

def test_build_history_passes_through_dicts(monkeypatch):
    """_build_history should return whatever get_conversation_history yields."""
    _mock_env(monkeypatch)

    fake_history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hallo!"},
    ]

    with patch(
        "services.pi_agent_client.get_conversation_history",
        return_value=fake_history,
    ):
        from services.pi_agent_client import _build_history
        result = _build_history(42)

    assert result == fake_history


# ─── chat() ───────────────────────────────────────────────────────────────────

def test_chat_posts_to_pi_agent_and_persists_messages(monkeypatch):
    """chat() should POST to /chat and persist user + assistant messages."""
    _mock_env(monkeypatch)

    from utils.crypto import encrypt
    encrypted = encrypt("sk-ant-key")
    mock_db = _mock_db_with_user(api_key_enc=encrypted)

    mock_client, mock_response = _build_async_httpx_mock(
        {"response": "Antwort vom Coach."}
    )

    add_message_mock = MagicMock()

    with patch("services.pi_agent_client.get_db", return_value=mock_db), \
         patch("services.pi_agent_client.httpx.AsyncClient", return_value=mock_client), \
         patch("services.pi_agent_client.add_message", add_message_mock), \
         patch(
             "services.pi_agent_client.get_conversation_history",
             return_value=[{"role": "user", "content": "alt"}],
         ):
        from services.pi_agent_client import chat
        result = asyncio.run(chat(7, "Lukas", "Wie war meine Woche?"))

    assert result == "Antwort vom Coach."

    # Verify HTTP POST shape
    mock_client.post.assert_called_once()
    call = mock_client.post.call_args
    assert call.args[0] == "http://test-pi-agent:3001/chat"
    payload = call.kwargs["json"]
    assert payload["user_id"] == 7
    assert payload["user_name"] == "Lukas"
    assert payload["message"] == "Wie war meine Woche?"
    assert payload["api_key"] == "sk-ant-key"
    assert payload["model"] == "claude-sonnet-4-20250514"
    assert payload["history"] == [{"role": "user", "content": "alt"}]

    # Verify both user + assistant messages were persisted
    assert add_message_mock.call_count == 2
    user_call, assistant_call = add_message_mock.call_args_list
    assert user_call.args == (7, "user", "Wie war meine Woche?")
    assert assistant_call.args == (7, "assistant", "Antwort vom Coach.")


def test_analyze_image_base64_encodes_and_posts(monkeypatch):
    """analyze_image() should base64-encode the bytes and POST to /analyze."""
    _mock_env(monkeypatch)

    from utils.crypto import encrypt
    encrypted = encrypt("sk-ant-key")
    mock_db = _mock_db_with_user(api_key_enc=encrypted)

    mock_client, _ = _build_async_httpx_mock({"response": "Schöne Form!"})

    with patch("services.pi_agent_client.get_db", return_value=mock_db), \
         patch("services.pi_agent_client.httpx.AsyncClient", return_value=mock_client), \
         patch("services.pi_agent_client.add_message"):
        from services.pi_agent_client import analyze_image
        result = asyncio.run(
            analyze_image(7, "Lukas", b"\xff\xd8\xff\xe0fake-jpg", caption="Squat-Check")
        )

    assert result == "Schöne Form!"

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["user_id"] == 7
    assert payload["message"] == "Squat-Check"
    assert payload["media_type"] == "image/jpeg"
    # Base64 of \xff\xd8\xff\xe0fake-jpg
    import base64
    expected_b64 = base64.standard_b64encode(b"\xff\xd8\xff\xe0fake-jpg").decode()
    assert payload["media_base64"] == expected_b64


def test_generate_morning_briefing_calls_briefing_endpoint(monkeypatch):
    """generate_morning_briefing() should POST to /briefing."""
    _mock_env(monkeypatch)

    from utils.crypto import encrypt
    encrypted = encrypt("sk-ant-key")
    mock_db = _mock_db_with_user(api_key_enc=encrypted)

    mock_client, _ = _build_async_httpx_mock({"response": "Briefing für heute..."})

    with patch("services.pi_agent_client.get_db", return_value=mock_db), \
         patch("services.pi_agent_client.httpx.AsyncClient", return_value=mock_client), \
         patch("services.pi_agent_client.add_message"):
        from services.pi_agent_client import generate_morning_briefing
        result = asyncio.run(generate_morning_briefing(7, "Lukas"))

    assert result == "Briefing für heute..."
    assert mock_client.post.call_args.args[0] == "http://test-pi-agent:3001/briefing"
