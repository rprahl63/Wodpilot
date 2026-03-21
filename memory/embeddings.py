"""
Embedding generation via OpenAI text-embedding-3-small.
Falls back to a simple zero vector if no API key is configured.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from config import get_config

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536


def get_embedding(text: str) -> List[float]:
    """Return a 1536-dim embedding vector for the given text."""
    api_key = get_config().openai_api_key
    if not api_key:
        logger.debug("No OpenAI key – using zero vector for embedding")
        return [0.0] * _EMBEDDING_DIM

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(input=text, model=_EMBEDDING_MODEL)
        return response.data[0].embedding
    except Exception as exc:
        logger.error("Embedding failed: %s", exc)
        return [0.0] * _EMBEDDING_DIM
