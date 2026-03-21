"""
Working Memory – last N messages of a conversation.
Stored in the `conversations` table and fetched on every agent call.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from db.client import get_db
from config import get_config


def get_conversation_history(user_id: int) -> List[Dict[str, str]]:
    """Return the last MAX_CONVERSATION_MESSAGES messages as pydantic-ai format."""
    db = get_db()
    limit = get_config().max_conversation_messages

    rows = (
        db.table("conversations")
        .select("role,content")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []

    # Reverse so oldest is first
    rows.reverse()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def add_message(user_id: int, role: str, content: str) -> None:
    """Persist a single message to conversation history."""
    db = get_db()
    db.table("conversations").insert(
        {
            "user_id": user_id,
            "role": role,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


def clear_history(user_id: int) -> None:
    """Delete all conversation history for a user."""
    db = get_db()
    db.table("conversations").delete().eq("user_id", user_id).execute()
