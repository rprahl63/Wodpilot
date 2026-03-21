"""Unit tests for the Fernet encryption utility."""
import os
import pytest
from cryptography.fernet import Fernet


def test_encrypt_decrypt(monkeypatch):
    """Encrypt and decrypt should round-trip correctly."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)

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
    monkeypatch.setenv("ENCRYPTION_KEY", key)

    import config
    config._config = None

    from utils.crypto import encrypt

    a = encrypt("password1")
    b = encrypt("password2")
    assert a != b
