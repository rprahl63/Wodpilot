"""
Episodic Memory – individual events with metadata.
Examples: 'Deadlift PR 145kg', 'Shoulder pain after snatches'.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.client import get_db
from memory.embeddings import get_embedding


def add_episode(
    user_id: int,
    content: str,
    category: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Add an episodic memory entry."""
    db = get_db()
    embedding = get_embedding(content)

    db.table("memory_episodes").insert(
        {
            "user_id": user_id,
            "content": content,
            "category": category,
            "metadata": metadata or {},
            "embedding": embedding,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


def search_episodes(user_id: int, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Semantically search episodic memory for a user."""
    db = get_db()
    embedding = get_embedding(query)

    try:
        result = db.rpc(
            "search_episodes",
            {
                "p_user_id": user_id,
                "p_embedding": embedding,
                "p_limit": limit,
            },
        ).execute()
        return result.data or []
    except Exception:
        # Fallback: simple text search
        rows = (
            db.table("memory_episodes")
            .select("content,category,metadata,created_at")
            .eq("user_id", user_id)
            .ilike("content", f"%{query}%")
            .limit(limit)
            .execute()
        ).data or []
        return rows


def get_prs(user_id: int) -> List[Dict[str, Any]]:
    """Return all PR episodes for a user."""
    db = get_db()
    return (
        db.table("memory_episodes")
        .select("content,metadata,created_at")
        .eq("user_id", user_id)
        .eq("category", "pr")
        .order("created_at", desc=True)
        .execute()
    ).data or []
