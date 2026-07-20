"""
Magic-link login tokens for the athlete dashboard.

Only the sha256 hash of a token is stored, so a database leak cannot be
replayed into a working login link. Tokens are single-use and expire after
`login_token_ttl_minutes` (default 15).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_config
from db.client import get_db


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_login_token(user_id: int) -> str:
    """Create a single-use login token for a user and return the raw token."""
    token = secrets.token_urlsafe(32)
    ttl = get_config().login_token_ttl_minutes
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    db = get_db()
    db.table("login_tokens").insert(
        {
            "user_id": user_id,
            "token_hash": _hash(token),
            "expires_at": expires.isoformat(),
        }
    ).execute()
    return token


def consume_login_token(token: str) -> Optional[int]:
    """
    Validate and consume a token. Returns the user_id, or None when the
    token is unknown, already used or expired.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    # Conditional update: only an unused token row is claimed, so a token
    # can never log in twice even with concurrent requests.
    rows = (
        db.table("login_tokens")
        .update({"used_at": now.isoformat()})
        .eq("token_hash", _hash(token))
        .is_("used_at", "null")
        .execute()
    ).data or []
    if not rows:
        return None
    row = rows[0]
    expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if expires_at < now:
        return None
    return row["user_id"]
