"""Fernet AES-128-CBC encryption for sensitive credentials."""
import base64
import os
from cryptography.fernet import Fernet
from config import get_config


def _get_fernet() -> Fernet:
    key = get_config().encryption_key
    # Accept both raw base64url Fernet keys and plain secrets
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        # Derive a valid Fernet key from the raw secret
        import hashlib
        raw = hashlib.sha256(key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(raw)
        return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext and return the plaintext."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def generate_key() -> str:
    """Generate a new Fernet key (use once during setup)."""
    return Fernet.generate_key().decode()
