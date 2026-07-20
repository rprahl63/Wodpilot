"""Unit tests for magic-link login tokens."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet


def _mock_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("SUPABASE_URL", "https://dummy.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "dummy")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("LOGIN_TOKEN_TTL_MINUTES", "15")

    import config
    config._config = None


def _mock_db_for_consume(rows: list[dict]):
    """Supabase mock whose conditional update returns the given rows."""
    mock_db = MagicMock()
    chain = mock_db.table.return_value.update.return_value.eq.return_value.is_.return_value
    chain.execute.return_value.data = rows
    return mock_db


def test_create_login_token_stores_only_the_hash(monkeypatch):
    """The raw token is returned but never written to the database."""
    _mock_env(monkeypatch)
    mock_db = MagicMock()

    with patch("services.login_tokens.get_db", return_value=mock_db):
        from services.login_tokens import create_login_token
        token = create_login_token(7)

    assert len(token) > 20
    inserted = mock_db.table.return_value.insert.call_args.args[0]
    assert inserted["user_id"] == 7
    assert inserted["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(inserted)


def test_create_login_token_honours_ttl(monkeypatch):
    """expires_at should be roughly TTL minutes in the future."""
    _mock_env(monkeypatch)
    monkeypatch.setenv("LOGIN_TOKEN_TTL_MINUTES", "5")
    import config
    config._config = None

    mock_db = MagicMock()
    with patch("services.login_tokens.get_db", return_value=mock_db):
        from services.login_tokens import create_login_token
        create_login_token(7)

    inserted = mock_db.table.return_value.insert.call_args.args[0]
    expires = datetime.fromisoformat(inserted["expires_at"])
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(minutes=4) < delta <= timedelta(minutes=5)


def test_consume_login_token_returns_user_id(monkeypatch):
    """A valid, unused, unexpired token yields its user_id."""
    _mock_env(monkeypatch)
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    mock_db = _mock_db_for_consume([{"user_id": 7, "expires_at": future}])

    with patch("services.login_tokens.get_db", return_value=mock_db):
        from services.login_tokens import consume_login_token
        assert consume_login_token("some-token") == 7


def test_consume_login_token_rejects_expired(monkeypatch):
    """An expired token is claimed but must not log anyone in."""
    _mock_env(monkeypatch)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    mock_db = _mock_db_for_consume([{"user_id": 7, "expires_at": past}])

    with patch("services.login_tokens.get_db", return_value=mock_db):
        from services.login_tokens import consume_login_token
        assert consume_login_token("expired-token") is None


def test_consume_login_token_rejects_second_use(monkeypatch):
    """The conditional update matches nothing once used_at is set."""
    _mock_env(monkeypatch)
    mock_db = _mock_db_for_consume([])

    with patch("services.login_tokens.get_db", return_value=mock_db):
        from services.login_tokens import consume_login_token
        assert consume_login_token("already-used") is None


def test_consume_login_token_looks_up_by_hash(monkeypatch):
    """Lookup uses the sha256 hash, never the raw token."""
    _mock_env(monkeypatch)
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    mock_db = _mock_db_for_consume([{"user_id": 7, "expires_at": future}])

    with patch("services.login_tokens.get_db", return_value=mock_db):
        from services.login_tokens import consume_login_token
        consume_login_token("raw-token")

    eq_call = mock_db.table.return_value.update.return_value.eq.call_args
    assert eq_call.args == (
        "token_hash",
        hashlib.sha256(b"raw-token").hexdigest(),
    )
