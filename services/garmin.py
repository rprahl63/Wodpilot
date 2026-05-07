"""
Garmin Connect integration.

Uses the unofficial garminconnect Python library.
Credentials are stored encrypted in Supabase.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from db.client import get_db
from services.training_load import DailyLoad, TrainingLoad, calculate_hr_tss, calculate_load
from utils.crypto import decrypt

logger = logging.getLogger(__name__)


def _get_garmin_client(garmin_email: str, garmin_password_enc: str):
    """Lazy-import garminconnect so the module remains importable without it."""
    import garminconnect  # type: ignore
    password = decrypt(garmin_password_enc)
    client = garminconnect.Garmin(garmin_email, password)
    client.login()
    return client


def sync_user_activities(user_id: int) -> int:
    """Fetch latest Garmin activities for a user and upsert into DB. Returns count synced."""
    db = get_db()

    user_row = (
        db.table("users")
        .select("garmin_email,garmin_password_enc,hr_max,hr_rest")
        .eq("id", user_id)
        .single()
        .execute()
    ).data
    if not user_row or not user_row.get("garmin_email"):
        logger.info("User %s has no Garmin credentials – skipping sync", user_id)
        return 0

    try:
        client = _get_garmin_client(
            user_row["garmin_email"], user_row["garmin_password_enc"]
        )
    except Exception as exc:
        logger.error("Garmin login failed for user %s: %s", user_id, exc)
        return 0

    hr_max = user_row.get("hr_max") or 190

    # Fetch last 100 activities
    try:
        raw_activities: List[Dict[str, Any]] = client.get_activities(0, 100)
    except Exception as exc:
        logger.error("Failed to fetch activities for user %s: %s", user_id, exc)
        return 0

    count = 0
    for act in raw_activities:
        garmin_id = str(act.get("activityId", ""))
        started_at_str = act.get("startTimeLocal") or act.get("startTimeGMT", "")
        try:
            started_at = datetime.fromisoformat(started_at_str).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue

        duration_s = int(act.get("duration", 0))
        hr_avg = act.get("averageHR") or act.get("maxHR")
        distance_m = act.get("distance", 0) or 0
        activity_type = (
            act.get("activityType", {}).get("typeKey", "unknown")
            if isinstance(act.get("activityType"), dict)
            else str(act.get("activityType", "unknown"))
        )
        calories = act.get("calories", 0) or 0

        tss = 0.0
        if hr_avg and duration_s:
            tss = calculate_hr_tss(duration_s, int(hr_avg), hr_max)

        record = {
            "user_id": user_id,
            "garmin_id": garmin_id,
            "activity_type": activity_type,
            "started_at": started_at.isoformat(),
            "duration_s": duration_s,
            "distance_m": float(distance_m),
            "hr_avg": int(hr_avg) if hr_avg else None,
            "hr_max": act.get("maxHR"),
            "calories": int(calories),
            "tss": round(tss, 2),
            "raw_json": act,
        }

        db.table("activities").upsert(
            record, on_conflict="user_id,garmin_id"
        ).execute()
        count += 1

    logger.info("Synced %d activities for user %s", count, user_id)
    return count


def get_training_load(user_id: int, days: int = 90) -> TrainingLoad:
    """Compute ATL/CTL/TSB for a user from the last `days` days of stored activities."""
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = (
        db.table("activities")
        .select("started_at,tss,activity_type,distance_m")
        .eq("user_id", user_id)
        .gte("started_at", since)
        .order("started_at")
        .execute()
    ).data or []

    daily: Dict[str, float] = {}
    run_km_14d = 0.0
    cutoff_14d = datetime.now(timezone.utc) - timedelta(days=14)

    for row in rows:
        d = datetime.fromisoformat(row["started_at"]).date().isoformat()
        daily[d] = daily.get(d, 0.0) + (row.get("tss") or 0.0)

        # Running km last 14 days
        act_type = (row.get("activity_type") or "").lower()
        if "run" in act_type:
            try:
                started = datetime.fromisoformat(row["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if started >= cutoff_14d:
                    run_km_14d += (row.get("distance_m") or 0) / 1000
            except ValueError:
                pass

    from datetime import date
    daily_loads = [
        DailyLoad(date=date.fromisoformat(d), tss=tss)
        for d, tss in sorted(daily.items())
    ]
    return calculate_load(daily_loads, run_km_14d=run_km_14d)


def get_recent_activities(user_id: int, days: int = 7) -> List[Dict[str, Any]]:
    """Return raw activity rows for the last N days."""
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (
        db.table("activities")
        .select(
            "activity_type,started_at,duration_s,distance_m,hr_avg,calories,tss"
        )
        .eq("user_id", user_id)
        .gte("started_at", since)
        .order("started_at", desc=True)
        .execute()
    ).data or []
    return rows
