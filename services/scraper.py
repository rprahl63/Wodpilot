"""
WOD scraper – fetches WODs from configured CrossFit boxes.

WOD sources are stored in the `config` table as JSON:
[
  {"name": "CrossFit Mitte", "url": "https://...", "selector": ".wod-content"},
  ...
]
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from db.client import get_db

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15  # seconds
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WODpilot/1.0; +https://wodpilot.app)"
    )
}


def _fetch_wod(source: Dict[str, Any], target_date: date) -> Optional[str]:
    """
    Fetch the WOD from a single source.
    Returns the cleaned text content or None.
    """
    url: str = source.get("url", "")
    selector: str = source.get("selector", ".wod")

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_DEFAULT_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch WOD from %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    elements = soup.select(selector)
    if not elements:
        # Fallback: try common selectors
        for fallback in [".wod", "#wod", ".workout", ".daily-wod", "article", "main"]:
            elements = soup.select(fallback)
            if elements:
                break

    if not elements:
        logger.warning("No WOD found at %s with selector %s", url, selector)
        return None

    text = "\n\n".join(el.get_text(separator="\n", strip=True) for el in elements[:3])
    return text[:4000]  # cap at 4k chars


def scrape_all_wods(target_date: Optional[date] = None) -> int:
    """Scrape WODs from all configured sources and upsert into DB. Returns count."""
    if target_date is None:
        target_date = date.today()

    db = get_db()
    cfg_row = db.table("config").select("value").eq("key", "wod_sources").single().execute()
    sources: List[Dict[str, Any]] = []
    if cfg_row.data:
        try:
            sources = json.loads(cfg_row.data["value"])
        except (json.JSONDecodeError, KeyError):
            sources = []

    if not sources:
        logger.info("No WOD sources configured – skipping scrape")
        return 0

    count = 0
    for source in sources:
        name = source.get("name", source.get("url", "unknown"))
        content = _fetch_wod(source, target_date)
        if not content:
            continue

        db.table("wods").upsert(
            {
                "date": target_date.isoformat(),
                "source": name,
                "content": content,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="date,source",
        ).execute()
        count += 1
        logger.info("Scraped WOD from %s for %s", name, target_date)

    return count


def get_todays_wods() -> List[Dict[str, Any]]:
    """Return today's WODs from the database."""
    db = get_db()
    today = date.today().isoformat()
    rows = (
        db.table("wods")
        .select("source,content,scraped_at")
        .eq("date", today)
        .execute()
    ).data or []
    return rows
