"""
Product issues – bug reports and feature requests about WODpilot itself.

The coach agent raises them from chat, a dev session works them off through the
MCP server. `status` is the workflow: open → in_progress → done | rejected.

Reaching a final status notifies the reporter on Telegram, which is why that
lives here and not in the MCP server: the admin dashboard changes status too
and must behave identically.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.client import get_db

logger = logging.getLogger(__name__)

KINDS = ("bug", "feature", "question", "other")
PRIORITIES = ("low", "normal", "high")
STATUSES = ("open", "in_progress", "done", "rejected")
FINAL_STATUSES = ("done", "rejected")

# High first – a list ordered purely by date buries the urgent report.
_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}

# Embeds the reporter so callers can show a name without a second round-trip.
_SELECT = "*, users(full_name, username, telegram_id)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_issue(
    user_id: int,
    title: str,
    body: str = "",
    kind: str = "other",
    priority: str = "normal",
    source: str = "chat",
) -> Dict[str, Any]:
    """Store a new issue and return the created row."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Titel erforderlich")
    if kind not in KINDS:
        kind = "other"
    if priority not in PRIORITIES:
        priority = "normal"

    db = get_db()
    rows = (
        db.table("issues")
        .insert(
            {
                "user_id": user_id,
                "title": title[:200],
                "body": (body or "").strip(),
                "kind": kind,
                "priority": priority,
                "source": source,
                "status": "open",
            }
        )
        .execute()
    ).data or []
    return rows[0]


def list_issues(
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Return issues, most urgent first.

    `status` accepts a single status or "open,in_progress" for the backlog view.
    """
    db = get_db()
    query = db.table("issues").select(_SELECT)
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        query = query.in_("status", wanted) if len(wanted) > 1 else query.eq("status", wanted[0])
    if user_id is not None:
        query = query.eq("user_id", user_id)
    rows = (query.order("created_at", desc=True).limit(limit).execute()).data or []
    rows.sort(key=lambda r: _PRIORITY_RANK.get(r.get("priority"), 1))
    return rows


def get_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """Return a single issue including its reporter, or None."""
    db = get_db()
    rows = (
        db.table("issues").select(_SELECT).eq("id", issue_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def claim_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """
    Atomically flip open → in_progress.

    Returns None when the issue was not 'open' anymore, so two parallel dev
    sessions can never work the same issue without noticing.
    """
    db = get_db()
    rows = (
        db.table("issues")
        .update({"status": "in_progress"})
        .eq("id", issue_id)
        .eq("status", "open")
        .execute()
    ).data or []
    return get_issue(rows[0]["id"]) if rows else None


def set_issue_status(
    issue_id: int,
    status: str,
    resolution: Optional[str] = None,
    notify: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Move an issue to `status`, notifying the reporter on a final status.

    A failed notification is logged and leaves `notified_at` NULL – a delivery
    problem must never roll back the status change.
    """
    if status not in STATUSES:
        raise ValueError(f"Ungültiger Status: {status}")

    issue = get_issue(issue_id)
    if issue is None:
        return None

    update: Dict[str, Any] = {"status": status}
    if resolution is not None:
        update["resolution"] = resolution.strip()
    if status in FINAL_STATUSES:
        update["resolved_at"] = _now_iso()
    else:
        # Reopening clears the outcome, otherwise a stale resolution would
        # still be shown next to an issue that is open again.
        update["resolved_at"] = None
        update["notified_at"] = None

    # Saving the same final status twice – an admin clicking "Speichern" again –
    # must not ping the athlete a second time. A retry after a failed send still
    # goes through, because notified_at is only set once Telegram accepted it.
    should_notify = (
        notify
        and status in FINAL_STATUSES
        and (issue["status"] != status or not issue.get("notified_at"))
    )

    db = get_db()
    rows = (db.table("issues").update(update).eq("id", issue_id).execute()).data or []
    if not rows:
        return None

    if should_notify:
        _notify_reporter(issue, status, update.get("resolution") or issue.get("resolution"))

    return get_issue(issue_id)


def _notify_reporter(
    issue: Dict[str, Any], status: str, resolution: Optional[str]
) -> None:
    """Tell the reporter their issue was resolved. Never raises."""
    telegram_id = (issue.get("users") or {}).get("telegram_id")
    if not telegram_id:
        logger.warning("Issue %s has no reporter to notify", issue["id"])
        return

    if status == "done":
        text = f"✅ Erledigt: {issue['title']}"
    else:
        text = f"🚫 Nicht umgesetzt: {issue['title']}"
    if resolution:
        text += f"\n\n{resolution}"

    from utils.telegram import notify_user

    if notify_user(telegram_id, text):
        get_db().table("issues").update({"notified_at": _now_iso()}).eq(
            "id", issue["id"]
        ).execute()


def format_issue_line(issue: Dict[str, Any]) -> str:
    """One-line rendering for the Telegram /issues list."""
    icons = {"open": "🆕", "in_progress": "🔧", "done": "✅", "rejected": "🚫"}
    kinds = {"bug": "Bug", "feature": "Feature", "question": "Frage", "other": "Sonstiges"}
    icon = icons.get(issue["status"], "•")
    kind = kinds.get(issue["kind"], issue["kind"])
    return f"{icon} #{issue['id']} [{kind}] {issue['title']}"
