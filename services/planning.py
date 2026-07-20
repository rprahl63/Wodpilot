"""
Weekly training plans – preferences, plan/session storage and the Sunday
planning state machine.

A `training_plans` row exists per user per week; its `status` column tracks
the Sunday flow: asked → planning → planned | failed. The transition
asked → planning is a conditional update so that the user's reply and the
18:00 fallback job can never both trigger planning for the same week.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from db.client import get_db

SESSION_TYPES = ("intervals", "run", "strength", "wod", "mobility", "rest")


# ─── Date helpers ─────────────────────────────────────────────────────────────

def current_week_start(today: Optional[date] = None) -> date:
    """Monday of the week containing `today` (dashboard default view)."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def upcoming_week_start(today: Optional[date] = None) -> date:
    """Next Monday strictly after `today` – the week the Sunday jobs plan for."""
    today = today or date.today()
    return today + timedelta(days=7 - today.weekday())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Preferences ──────────────────────────────────────────────────────────────

def get_preferences(user_id: int) -> str:
    """Return the user's free-text training preferences ('' if none)."""
    db = get_db()
    rows = (
        db.table("training_preferences")
        .select("preferences_text")
        .eq("user_id", user_id)
        .execute()
    ).data or []
    return rows[0]["preferences_text"] if rows else ""


def save_preferences(user_id: int, text: str) -> None:
    """Create or update the user's training preferences."""
    db = get_db()
    db.table("training_preferences").upsert(
        {"user_id": user_id, "preferences_text": text},
        on_conflict="user_id",
    ).execute()


# ─── Plans & sessions ─────────────────────────────────────────────────────────

def get_week_plan(user_id: int, week_start: date | str) -> Optional[Dict[str, Any]]:
    """Return the plan row for the week plus its sessions (ordered), or None."""
    db = get_db()
    ws = week_start.isoformat() if isinstance(week_start, date) else week_start
    plans = (
        db.table("training_plans")
        .select("*")
        .eq("user_id", user_id)
        .eq("week_start", ws)
        .execute()
    ).data or []
    if not plans:
        return None
    plan = plans[0]
    sessions = (
        db.table("plan_sessions")
        .select("*")
        .eq("plan_id", plan["id"])
        .order("date")
        .order("position")
        .execute()
    ).data or []
    plan["sessions"] = sessions
    return plan


def mark_week_asked(user_id: int, week_start: date | str) -> Optional[Dict[str, Any]]:
    """
    Ensure a plan row in status 'asked' exists for the week.

    Returns the row, or None when the week is already planning/planned
    (in that case the Sunday question must not be re-sent).
    """
    db = get_db()
    ws = week_start.isoformat() if isinstance(week_start, date) else week_start
    existing = get_week_plan(user_id, ws)
    if existing:
        if existing["status"] in ("planning", "planned"):
            return None
        rows = (
            db.table("training_plans")
            .update({"status": "asked", "asked_at": _now_iso()})
            .eq("id", existing["id"])
            .execute()
        ).data or []
        return rows[0] if rows else existing
    rows = (
        db.table("training_plans")
        .insert({"user_id": user_id, "week_start": ws, "status": "asked", "asked_at": _now_iso()})
        .execute()
    ).data or []
    return rows[0] if rows else None


def get_pending_ask(user_id: int) -> Optional[Dict[str, Any]]:
    """Return the newest plan row still waiting for the user's reply, if any."""
    db = get_db()
    rows = (
        db.table("training_plans")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "asked")
        .gte("week_start", date.today().isoformat())
        .order("week_start", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def claim_planning(plan_id: int, constraints: Optional[str] = None) -> bool:
    """
    Atomically flip asked → planning (storing the user's reply, if any).

    Returns False when the row was not in 'asked' anymore – someone else
    (reply vs. fallback job) already claimed it.
    """
    db = get_db()
    update: Dict[str, Any] = {"status": "planning"}
    if constraints is not None:
        update["constraints_text"] = constraints
    rows = (
        db.table("training_plans")
        .update(update)
        .eq("id", plan_id)
        .eq("status", "asked")
        .execute()
    ).data or []
    return bool(rows)


def set_plan_failed(plan_id: int) -> None:
    """Mark a plan as failed so the fallback/replan can retry."""
    db = get_db()
    db.table("training_plans").update({"status": "failed"}).eq("id", plan_id).execute()


def save_week_plan(user_id: int, week_start: date | str, sessions: List[Dict[str, Any]]) -> int:
    """
    Replace the sessions of a week plan and mark it planned.

    Creates the plan row if missing (e.g. /replan without a Sunday ask).
    Returns the number of sessions stored.
    """
    db = get_db()
    ws = week_start.isoformat() if isinstance(week_start, date) else week_start
    plan = get_week_plan(user_id, ws)
    if plan is None:
        plan = (
            db.table("training_plans")
            .insert({"user_id": user_id, "week_start": ws, "status": "planning"})
            .execute()
        ).data[0]

    db.table("plan_sessions").delete().eq("plan_id", plan["id"]).execute()
    rows = [
        {
            "plan_id": plan["id"],
            "user_id": user_id,
            "date": s["date"],
            "position": s.get("position", i),
            "title": s["title"],
            "session_type": s.get("session_type"),
            "description": s["description"],
        }
        for i, s in enumerate(sessions)
    ]
    if rows:
        db.table("plan_sessions").insert(rows).execute()

    db.table("training_plans").update(
        {"status": "planned", "planned_at": _now_iso()}
    ).eq("id", plan["id"]).execute()
    return len(rows)


def log_session_result(
    user_id: int,
    session_id: Optional[int] = None,
    session_date: Optional[str] = None,
    status: str = "done",
    result_text: Optional[str] = None,
    rpe: Optional[int] = None,
    notes: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Store a result on a session, located by id (ownership-checked) or by date.

    Returns the updated session or None when no matching session exists.
    """
    if status not in ("done", "skipped", "planned"):
        raise ValueError(f"Ungültiger Status: {status}")

    db = get_db()
    query = db.table("plan_sessions").select("id").eq("user_id", user_id)
    if session_id is not None:
        query = query.eq("id", session_id)
    elif session_date is not None:
        query = query.eq("date", session_date)
    else:
        raise ValueError("session_id oder session_date erforderlich")
    matches = query.order("position").limit(1).execute().data or []
    if not matches:
        return None

    update: Dict[str, Any] = {"status": status}
    if result_text is not None:
        update["result_text"] = result_text
    if rpe is not None:
        update["rpe"] = rpe
    if notes is not None:
        update["result_notes"] = notes
    update["completed_at"] = _now_iso() if status in ("done", "skipped") else None

    rows = (
        db.table("plan_sessions")
        .update(update)
        .eq("id", matches[0]["id"])
        .execute()
    ).data or []
    return rows[0] if rows else None


def users_awaiting_plan(week_start: date | str) -> List[Dict[str, Any]]:
    """Return plan rows still in 'asked' for the week (for the fallback job)."""
    db = get_db()
    ws = week_start.isoformat() if isinstance(week_start, date) else week_start
    return (
        db.table("training_plans")
        .select("*")
        .eq("week_start", ws)
        .eq("status", "asked")
        .execute()
    ).data or []
