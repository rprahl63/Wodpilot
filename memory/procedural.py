"""
Procedural Memory – coaching style and preferences.
Learned from athlete feedback over time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from db.client import get_db


_DEFAULT_PROFILE = {
    "coaching_style": "balanced",
    "preferred_language": "de",
    "notes": "",
}


def get_coaching_profile(user_id: int) -> Dict[str, Any]:
    """Return the coaching profile for a user, or defaults."""
    db = get_db()
    row = (
        db.table("memory_procedural")
        .select("coaching_style,preferred_language,notes")
        .eq("user_id", user_id)
        .execute()
    ).data

    if row:
        return row[0]
    return _DEFAULT_PROFILE.copy()


def update_coaching_style(
    user_id: int,
    coaching_style: Optional[str] = None,
    preferred_language: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    """Update coaching style preferences for a user."""
    db = get_db()
    update: Dict[str, Any] = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    if coaching_style:
        assert coaching_style in ("direct", "supportive", "technical", "balanced")
        update["coaching_style"] = coaching_style
    if preferred_language:
        update["preferred_language"] = preferred_language
    if notes is not None:
        update["notes"] = notes

    db.table("memory_procedural").upsert(update, on_conflict="user_id").execute()
