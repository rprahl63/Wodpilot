"""
Athlete-facing dashboard – week plan, results and training preferences.

Athletes never get a password: the Telegram bot sends a single-use magic link
(/dashboard), which this blueprint exchanges for a session. The athlete session
lives in a separate key from the admin one, so both can coexist in one browser.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import wraps
from typing import Any, Optional

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

logger = logging.getLogger(__name__)

athlete_bp = Blueprint("athlete", __name__, url_prefix="/me")

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def athlete_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("athlete_user_id"):
            return render_template("athlete_login_error.html"), 401
        return f(*args, **kwargs)
    return decorated


def _current_athlete() -> dict[str, Any]:
    from db.client import get_db

    user_id = session["athlete_user_id"]
    row = (
        get_db()
        .table("users")
        .select("id,full_name,username")
        .eq("id", user_id)
        .execute()
    ).data
    if not row:
        # User was deleted while the session was alive.
        session.pop("athlete_user_id", None)
        abort(401)
    return row[0]


def _parse_week(raw: Optional[str]) -> date:
    from services.planning import current_week_start

    if raw:
        try:
            return current_week_start(date.fromisoformat(raw))
        except ValueError:
            pass
    return current_week_start()


@athlete_bp.route("/auth/<token>")
def auth(token: str):
    from services.login_tokens import consume_login_token

    user_id = consume_login_token(token)
    if not user_id:
        return render_template("athlete_login_error.html"), 401

    session["athlete_user_id"] = user_id
    session.permanent = True
    return redirect(url_for("athlete.week"))


@athlete_bp.route("/logout")
def logout():
    # Only drop the athlete session – an admin session in the same browser stays.
    session.pop("athlete_user_id", None)
    return render_template("athlete_login_error.html", logged_out=True)


@athlete_bp.route("/")
@athlete_required
def week():
    from services.planning import get_week_plan

    user = _current_athlete()
    week_start = _parse_week(request.args.get("week"))
    plan = get_week_plan(user["id"], week_start)

    # Group sessions by day so the template can render Monday–Sunday.
    sessions_by_date: dict[str, list[dict[str, Any]]] = {}
    for s in (plan or {}).get("sessions", []):
        sessions_by_date.setdefault(str(s["date"]), []).append(s)

    days = [
        {
            "date": week_start + timedelta(days=i),
            "label": WEEKDAYS[i],
            "sessions": sessions_by_date.get((week_start + timedelta(days=i)).isoformat(), []),
        }
        for i in range(7)
    ]

    return render_template(
        "athlete_week.html",
        user=user,
        plan=plan,
        days=days,
        week_start=week_start,
        prev_week=week_start - timedelta(days=7),
        next_week=week_start + timedelta(days=7),
        today=date.today(),
    )


@athlete_bp.route("/preferences", methods=["GET", "POST"])
@athlete_required
def preferences():
    from services.planning import get_preferences, save_preferences

    user = _current_athlete()
    if request.method == "POST":
        save_preferences(user["id"], request.form.get("preferences_text", "").strip())
        flash("Trainingspräferenzen gespeichert.", "success")
        return redirect(url_for("athlete.preferences"))

    return render_template(
        "athlete_preferences.html", user=user, preferences=get_preferences(user["id"])
    )


@athlete_bp.route("/sessions/<int:session_id>/result", methods=["POST"])
@athlete_required
def session_result(session_id: int):
    from services.planning import log_session_result

    user = _current_athlete()
    status = request.form.get("status", "done")
    if status not in ("done", "skipped", "planned"):
        abort(400)

    rpe_raw = request.form.get("rpe", "").strip()
    rpe = None
    if rpe_raw:
        try:
            rpe = int(rpe_raw)
        except ValueError:
            flash("RPE muss eine Zahl zwischen 1 und 10 sein.", "danger")
            return redirect(url_for("athlete.week", week=request.form.get("week")))
        if not 1 <= rpe <= 10:
            flash("RPE muss zwischen 1 und 10 liegen.", "danger")
            return redirect(url_for("athlete.week", week=request.form.get("week")))

    # log_session_result filters by user_id, so a foreign session id finds nothing.
    result = log_session_result(
        user["id"],
        session_id=session_id,
        status=status,
        result_text=request.form.get("result_text", "").strip() or None,
        rpe=rpe,
        notes=request.form.get("result_notes", "").strip() or None,
    )
    if result is None:
        abort(404)

    flash("Ergebnis gespeichert.", "success")
    return redirect(url_for("athlete.week", week=request.form.get("week")))
