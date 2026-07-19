"""
Embedding generation via the Requesty router.

Keys are per-user (BYOK), same as the chat models — the caller passes the
user_id and we decrypt that user's key. Falls back to a service-wide key if
one is configured.

Returns None when no embedding can be produced. Callers must store NULL in
that case: a zero vector is worse than nothing, because pgvector's cosine
distance against it is NaN, which silently randomises the ranking of a
similarity search instead of excluding the row.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from config import get_config

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
_TIMEOUT = 20.0


def _resolve_api_key(user_id: Optional[int]) -> Optional[str]:
    """The user's Requesty key, else the service-wide one, else None."""
    cfg = get_config()

    if user_id is not None:
        try:
            # Imported lazily to keep this module free of a hard dependency on
            # the DB layer at import time.
            from db.client import get_db
            from utils.crypto import decrypt

            row = (
                get_db()
                .table("users")
                .select("llm_api_key_enc")
                .eq("id", user_id)
                .single()
                .execute()
            ).data
            if row and row.get("llm_api_key_enc"):
                return decrypt(row["llm_api_key_enc"])
        except Exception as exc:
            logger.warning("Could not load Requesty key for user %s: %s", user_id, exc)

    return cfg.requesty_api_key or None


def get_embedding(text: str, user_id: Optional[int] = None) -> Optional[List[float]]:
    """Return a 1536-dim embedding, or None if it could not be generated."""
    api_key = _resolve_api_key(user_id)
    if not api_key:
        logger.debug("No Requesty key available – storing NULL embedding")
        return None

    cfg = get_config()
    # text-embedding-3-large is noticeably better at German queries against
    # English-stored memories, and its `dimensions` parameter lets us keep the
    # native 1536-wide column instead of migrating to 3072.
    payload: dict = {
        "model": cfg.embedding_model,
        "input": text,
        "dimensions": EMBEDDING_DIM,
    }
    try:
        resp = httpx.post(
            f"{cfg.requesty_base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        vector = resp.json()["data"][0]["embedding"]
    except Exception as exc:
        logger.error("Embedding failed: %s", exc)
        return None

    if len(vector) != EMBEDDING_DIM:
        # The column is vector(1536); anything else would be rejected by
        # Postgres anyway, so fail here where the cause is still visible.
        logger.error(
            "Embedding model %s returned %d dims, expected %d",
            cfg.embedding_model,
            len(vector),
            EMBEDDING_DIM,
        )
        return None

    return vector
