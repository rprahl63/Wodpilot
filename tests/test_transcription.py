"""Unit tests for voice-message transcription via the Requesty router."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet


def _mock_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("SUPABASE_URL", "https://dummy.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "dummy")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("REQUESTY_BASE_URL", "https://router.test/v1")
    monkeypatch.delenv("REQUESTY_API_KEY", raising=False)

    import config
    config._config = None


def _mock_db_with_key(encrypted: str | None):
    """Supabase mock returning a user row with the given encrypted key."""
    mock_db = MagicMock()
    chain = mock_db.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = (
        {"llm_api_key_enc": encrypted} if encrypted else None
    )
    return mock_db


def _mock_httpx(json_response: dict, raises: Exception | None = None):
    """Mock httpx.AsyncClient whose .post() returns the given JSON."""
    mock_response = MagicMock()
    mock_response.json.return_value = json_response
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=raises) if raises else AsyncMock(
        return_value=mock_response
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ─── filename_for ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "mime,expected",
    [
        ("audio/ogg", "voice.ogg"),      # Telegram voice notes
        ("audio/mpeg", "voice.mp3"),
        ("audio/x-m4a", "voice.m4a"),
        ("AUDIO/WAV", "voice.wav"),      # case-insensitive
        ("audio/exotic", "voice.ogg"),   # unknown falls back to ogg
        (None, "voice.ogg"),
    ],
)
def test_filename_for_maps_mime_to_extension(monkeypatch, mime, expected):
    """Requesty picks its decoder from the extension, so it must be right."""
    _mock_env(monkeypatch)
    from services.transcription import filename_for
    assert filename_for(mime) == expected


# ─── transcribe ───────────────────────────────────────────────────────────────

def test_transcribe_posts_multipart_with_user_key(monkeypatch):
    """The athlete's own key pays for the transcription (BYOK)."""
    _mock_env(monkeypatch)
    from utils.crypto import encrypt
    mock_db = _mock_db_with_key(encrypt("rqsty-user-key"))
    mock_client = _mock_httpx({"text": "  Hab heute 6x400 gemacht  "})

    with patch("db.client.get_db", return_value=mock_db), \
         patch("services.transcription.httpx.AsyncClient", return_value=mock_client):
        from services.transcription import transcribe
        result = asyncio.run(transcribe(b"fake-ogg-bytes", user_id=7, mime_type="audio/ogg"))

    assert result == "Hab heute 6x400 gemacht"

    call = mock_client.post.call_args
    assert call.args[0] == "https://router.test/v1/audio/transcriptions"
    assert call.kwargs["headers"]["Authorization"] == "Bearer rqsty-user-key"
    assert call.kwargs["files"]["file"][0] == "voice.ogg"
    assert call.kwargs["files"]["file"][1] == b"fake-ogg-bytes"
    assert call.kwargs["data"]["model"] == "openai/gpt-4o-mini-transcribe"
    assert call.kwargs["data"]["language"] == "de"


def test_transcribe_returns_none_without_key(monkeypatch):
    """No key means no transcription – and no crash."""
    _mock_env(monkeypatch)
    mock_db = _mock_db_with_key(None)

    with patch("db.client.get_db", return_value=mock_db):
        from services.transcription import transcribe
        assert asyncio.run(transcribe(b"audio", user_id=7)) is None


def test_transcribe_returns_none_on_http_error(monkeypatch):
    """An upstream failure surfaces as None, not an exception."""
    _mock_env(monkeypatch)
    from utils.crypto import encrypt
    mock_db = _mock_db_with_key(encrypt("rqsty-user-key"))
    mock_client = _mock_httpx({}, raises=RuntimeError("502"))

    with patch("db.client.get_db", return_value=mock_db), \
         patch("services.transcription.httpx.AsyncClient", return_value=mock_client):
        from services.transcription import transcribe
        assert asyncio.run(transcribe(b"audio", user_id=7)) is None


def test_transcribe_returns_none_for_blank_transcript(monkeypatch):
    """Silence must not be forwarded to the agent as an empty message."""
    _mock_env(monkeypatch)
    from utils.crypto import encrypt
    mock_db = _mock_db_with_key(encrypt("rqsty-user-key"))
    mock_client = _mock_httpx({"text": "   "})

    with patch("db.client.get_db", return_value=mock_db), \
         patch("services.transcription.httpx.AsyncClient", return_value=mock_client):
        from services.transcription import transcribe
        assert asyncio.run(transcribe(b"audio", user_id=7)) is None


def test_transcribe_rejects_oversized_audio(monkeypatch):
    """Files above Requesty's limit are refused before uploading."""
    _mock_env(monkeypatch)
    from services.transcription import MAX_AUDIO_BYTES, transcribe

    with patch("services.transcription.httpx.AsyncClient") as mock_client:
        result = asyncio.run(transcribe(b"x" * (MAX_AUDIO_BYTES + 1), user_id=7))

    assert result is None
    mock_client.assert_not_called()


def test_transcribe_rejects_empty_audio(monkeypatch):
    """Empty bytes short-circuit without an API call."""
    _mock_env(monkeypatch)
    from services.transcription import transcribe

    with patch("services.transcription.httpx.AsyncClient") as mock_client:
        assert asyncio.run(transcribe(b"", user_id=7)) is None

    mock_client.assert_not_called()


def test_transcribe_falls_back_to_service_key(monkeypatch):
    """A service-wide key is used when the user has none."""
    _mock_env(monkeypatch)
    monkeypatch.setenv("REQUESTY_API_KEY", "rqsty-service-key")
    import config
    config._config = None

    mock_db = _mock_db_with_key(None)
    mock_client = _mock_httpx({"text": "Servus"})

    with patch("db.client.get_db", return_value=mock_db), \
         patch("services.transcription.httpx.AsyncClient", return_value=mock_client):
        from services.transcription import transcribe
        result = asyncio.run(transcribe(b"audio", user_id=7))

    assert result == "Servus"
    auth = mock_client.post.call_args.kwargs["headers"]["Authorization"]
    assert auth == "Bearer rqsty-service-key"
