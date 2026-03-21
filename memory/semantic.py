"""
Semantic Memory – key-value facts with pgvector embeddings.
Examples: PRs, injuries, preferences, goals.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.client import get_db
from memory.embeddings import get_embedding

logger = logging.getLogger(__name__)


def save_memory(user_id: int, key: str, value: str, category: Optional[str] = None) -> None:
    """Upsert a key-value fact into semantic memory."""
    db = get_db()
    embedding = get_embedding(f"{key}: {value}")

    db.table("coach_memory").upsert(
        {
            "user_id": user_id,
            "key": key,
            "value": value,
            "category": category,
            "embedding": embedding,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,key",
    ).execute()


def search_memory(user_id: int, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Semantically search memory entries for a user."""
    db = get_db()
    embedding = get_embedding(query)

    try:
        # Use Supabase RPC for vector similarity search
        result = db.rpc(
            "search_coach_memory",
            {
                "p_user_id": user_id,
                "p_embedding": embedding,
                "p_limit": limit,
            },
        ).execute()
        return result.data or []
    except Exception:
        # Fallback: simple text search without vector
        rows = (
            db.table("coach_memory")
            .select("key,value,category")
            .eq("user_id", user_id)
            .ilike("value", f"%{query}%")
            .limit(limit)
            .execute()
        ).data or []
        return rows


def get_all_memories(user_id: int) -> List[Dict[str, Any]]:
    """Return all memory entries for a user."""
    db = get_db()
    return (
        db.table("coach_memory")
        .select("key,value,category,updated_at")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    ).data or []


def delete_memory(user_id: int, key: str) -> None:
    db = get_db()
    db.table("coach_memory").delete().eq("user_id", user_id).eq("key", key).execute()
