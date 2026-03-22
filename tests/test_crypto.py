"""Unit tests for the Fernet encryption utility."""
import os
import pytest
from cryptography.fernet import Fernet


def _mock_env(monkeypatch, key: str) -> None:
    """Set all required env vars for Config, using the given ENCRYPTION_KEY."""
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("SUPABASE_URL", "https://dummy.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "dummy")
    monkeypatch.setenv("ENCRYPTION_KEY", key)


def test_encrypt_decrypt(monkeypatch):
    """Encrypt and decrypt should round-trip correctly."""
    key = Fernet.generate_key().decode()
    _mock_env(monkeypatch, key)

    # Force re-init of config singleton
    import config
    config._config = None

    from utils.crypto import encrypt, decrypt

    plaintext = "super-secret-password-123!"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_different_plaintexts_give_different_ciphertexts(monkeypatch):
    key = Fernet.generate_key().decode()
    _mock_env(monkeypatch, key)

    import config
    config._config = None

    from utils.crypto import encrypt

    a = encrypt("password1")
    b = encrypt("password2")
    assert a != b
