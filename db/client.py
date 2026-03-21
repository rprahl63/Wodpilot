"""Supabase client – singleton, server-side service_role key only."""
from __future__ import annotations

from typing import Optional

from supabase import create_client, Client
from config import get_config

_client: Optional[Client] = None


def get_db() -> Client:
    global _client
    if _client is None:
        cfg = get_config()
        _client = create_client(cfg.supabase_url, cfg.supabase_service_key)
    return _client
