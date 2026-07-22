"""
WODpilot Admin Dashboard – Flask application.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from config import get_config
from db.client import get_db
from utils.crypto import encrypt, decrypt
from utils.log import silence_http_client_logs

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    silence_http_client_logs()
    cfg = get_config()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = cfg.web_secret_key

    # ─── Auth ─────────────────────────────────────────────────────────────────

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            password = request.form.get("password", "")
            if password == cfg.web_admin_password:
                session["logged_in"] = True
                return redirect(url_for("dashboard"))
            error = "Falsches Passwort."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ─── Dashboard ────────────────────────────────────────────────────────────

    @app.route("/")
    @login_required
    def dashboard():
        db = get_db()
        stats = {}
        stats["user_count"] = len((db.table("users").select("id").execute()).data or [])
        stats["activity_count"] = len((db.table("activities").select("id").execute()).data or [])
        stats["wod_count"] = len((db.table("wods").select("id").execute()).data or [])
        stats["memory_count"] = len((db.table("coach_memory").select("id").execute()).data or [])

        recent_users = (
            db.table("users")
            .select("id,telegram_id,username,full_name,created_at,garmin_email,llm_model")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        ).data or []

        return render_template("dashboard.html", stats=stats, recent_users=recent_users)

    # ─── Users ────────────────────────────────────────────────────────────────

    @app.route("/users")
    @login_required
    def users():
        db = get_db()
        all_users = (
            db.table("users")
            .select("id,telegram_id,username,full_name,role,garmin_email,llm_model,briefing_enabled,created_at,api_calls_today")
            .order("created_at", desc=True)
            .execute()
        ).data or []
        return render_template("users.html", users=all_users)

    @app.route("/users/<int:user_id>", methods=["GET", "POST"])
    @login_required
    def user_detail(user_id: int):
        db = get_db()
        user_row = (
            db.table("users")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        ).data
        if not user_row:
            abort(404)

        if request.method == "POST":
            action = request.form.get("action")
            if action == "update_profile":
                updates: dict[str, Any] = {
                    "hr_max": int(request.form.get("hr_max", 190) or 190),
                    "hr_rest": int(request.form.get("hr_rest", 55) or 55),
                    "llm_model": request.form.get("llm_model", "anthropic/claude-sonnet-4-5"),
                    "timezone": request.form.get("timezone", "Europe/Berlin"),
                    "briefing_enabled": request.form.get("briefing_enabled") == "on",
                }
                new_api_key = request.form.get("llm_api_key", "").strip()
                if new_api_key:
                    updates["llm_api_key_enc"] = encrypt(new_api_key)
                db.table("users").update(updates).eq("id", user_id).execute()
                flash("Profil aktualisiert.", "success")
            elif action == "delete":
                db.table("users").delete().eq("id", user_id).execute()
                flash(f"User {user_id} gelöscht.", "warning")
                return redirect(url_for("users"))

            return redirect(url_for("user_detail", user_id=user_id))

        # Load memory
        memories = (
            db.table("coach_memory")
            .select("key,value,category,updated_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(20)
            .execute()
        ).data or []

        episodes = (
            db.table("memory_episodes")
            .select("content,category,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        ).data or []

        return render_template(
            "user_detail.html", user=user_row, memories=memories, episodes=episodes
        )

    @app.route("/users/<int:user_id>/dashboard")
    @login_required
    def view_as_athlete(user_id: int):
        """Open an athlete's dashboard from the admin UI.

        Same impersonation the admin chat already does, just for the web view.
        The admin session stays untouched, so leaving the athlete view lands
        back in the admin area.
        """
        row = (
            get_db().table("users").select("id").eq("id", user_id).execute()
        ).data
        if not row:
            abort(404)
        session["athlete_user_id"] = user_id
        return redirect(url_for("athlete.week"))

    # ─── Invite codes ─────────────────────────────────────────────────────────

    @app.route("/codes", methods=["GET", "POST"])
    @login_required
    def codes():
        db = get_db()
        if request.method == "POST":
            count = int(request.form.get("count", 1))
            expires_days = request.form.get("expires_days", "")
            expires_at = None
            if expires_days:
                from datetime import timedelta
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(days=int(expires_days))
                ).isoformat()

            new_codes = []
            for _ in range(min(count, 50)):
                code = secrets.token_urlsafe(8)
                db.table("invite_codes").insert(
                    {"code": code, "expires_at": expires_at}
                ).execute()
                new_codes.append(code)
            flash(f"{len(new_codes)} Code(s) erstellt: {', '.join(new_codes)}", "success")

        all_codes = (
            db.table("invite_codes")
            .select("id,code,used_by,expires_at,created_at")
            .order("created_at", desc=True)
            .execute()
        ).data or []

        return render_template("codes.html", codes=all_codes)

    @app.route("/codes/<int:code_id>/delete", methods=["POST"])
    @login_required
    def delete_code(code_id: int):
        db = get_db()
        db.table("invite_codes").delete().eq("id", code_id).execute()
        flash("Code gelöscht.", "warning")
        return redirect(url_for("codes"))

    # ─── WODs ─────────────────────────────────────────────────────────────────

    @app.route("/wods")
    @login_required
    def wods():
        db = get_db()
        wod_list = (
            db.table("wods")
            .select("id,date,source,content,scraped_at")
            .order("date", desc=True)
            .limit(50)
            .execute()
        ).data or []
        return render_template("wods.html", wods=wod_list)

    # ─── Issues ───────────────────────────────────────────────────────────────

    @app.route("/issues")
    @login_required
    def issues():
        from services.issues import list_issues
        status = request.args.get("status") or "open,in_progress"
        issue_list = list_issues(status=None if status == "all" else status, limit=200)
        return render_template("issues.html", issues=issue_list, status=status)

    @app.route("/issues/<int:issue_id>/status", methods=["POST"])
    @login_required
    def issue_status(issue_id: int):
        from services.issues import set_issue_status
        status = request.form.get("status", "")
        resolution = request.form.get("resolution") or None
        try:
            updated = set_issue_status(issue_id, status, resolution=resolution)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("issues"))
        if updated is None:
            flash(f"Issue #{issue_id} nicht gefunden.", "warning")
        else:
            flash(f"Issue #{issue_id} → {status}.", "success")
        return redirect(request.referrer or url_for("issues"))

    # ─── Config ───────────────────────────────────────────────────────────────

    @app.route("/config", methods=["GET", "POST"])
    @login_required
    def config_page():
        db = get_db()

        if request.method == "POST":
            # Update WOD sources
            sources_json = request.form.get("wod_sources", "[]")
            try:
                json.loads(sources_json)  # validate JSON
                db.table("config").upsert(
                    {"key": "wod_sources", "value": sources_json}
                ).execute()
                flash("Konfiguration gespeichert.", "success")
            except json.JSONDecodeError:
                flash("Ungültiges JSON für WOD-Quellen.", "danger")

            for key in [
                "garmin_sync_cron",
                "wod_scrape_cron",
                "morning_briefing_cron",
                "weekly_plan_ask_cron",
                "weekly_plan_fallback_cron",
            ]:
                val = request.form.get(key, "").strip()
                if val:
                    db.table("config").upsert({"key": key, "value": val}).execute()

        config_rows = (db.table("config").select("key,value").execute()).data or []
        config_map = {r["key"]: r["value"] for r in config_rows}
        return render_template("config.html", config=config_map)

    # ─── Manual triggers ──────────────────────────────────────────────────────

    @app.route("/trigger/garmin-sync", methods=["POST"])
    @login_required
    def trigger_garmin_sync():
        import asyncio
        from services.scheduler import job_garmin_sync
        asyncio.run(job_garmin_sync())
        flash("Garmin-Sync manuell ausgelöst.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/trigger/wod-scrape", methods=["POST"])
    @login_required
    def trigger_wod_scrape():
        import asyncio
        from services.scheduler import job_wod_scrape
        asyncio.run(job_wod_scrape())
        flash("WOD-Scrape manuell ausgelöst.", "success")
        return redirect(url_for("dashboard"))

    # ─── Model catalogue ──────────────────────────────────────────────────────

    @app.route("/api/models/<int:user_id>")
    @login_required
    def api_models(user_id: int):
        """Tool-capable Requesty models, for the picker on the user page.

        The key is decrypted server-side and handed to pi-agent; it never
        reaches the browser.
        """
        import httpx

        row = (
            get_db()
            .table("users")
            .select("llm_api_key_enc")
            .eq("id", user_id)
            .single()
            .execute()
        ).data
        if not row or not row.get("llm_api_key_enc"):
            return jsonify({"error": "Für diesen Nutzer ist kein API-Key hinterlegt."}), 400

        try:
            api_key = decrypt(row["llm_api_key_enc"])
        except Exception:
            logger.exception("Could not decrypt API key for user %s", user_id)
            return jsonify({"error": "API-Key nicht entschlüsselbar (ENCRYPTION_KEY geändert?)."}), 500

        try:
            resp = httpx.get(
                f"{cfg.pi_agent_url}/models",
                headers={"x-api-key": api_key},
                timeout=20.0,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Model catalogue unavailable: %s", exc)
            return jsonify({"error": f"Modell-Liste nicht abrufbar: {exc}"}), 502

        return jsonify(resp.json())

    # ─── Chat ─────────────────────────────────────────────────────────────────

    def _chat_users() -> list[dict[str, Any]]:
        """Users that can actually hold a conversation (i.e. have an LLM key)."""
        rows = (
            get_db()
            .table("users")
            .select("id,telegram_id,full_name,username,llm_api_key_enc,role")
            .order("id")
            .execute()
        ).data or []
        return [r for r in rows if r.get("llm_api_key_enc")]

    @app.route("/chat")
    @login_required
    def chat_page():
        from memory.working import get_conversation_history

        users = _chat_users()
        if not users:
            return render_template("chat.html", users=[], user_id=None, history=[])

        # Default to the admin's own record, else the first eligible user.
        requested = request.args.get("user_id", type=int)
        valid_ids = {u["id"] for u in users}
        if requested in valid_ids:
            user_id = requested
        else:
            admins = [u for u in users if u.get("role") == "admin"]
            user_id = (admins or users)[0]["id"]

        return render_template(
            "chat.html",
            users=users,
            user_id=user_id,
            history=get_conversation_history(user_id),
        )

    @app.route("/chat/send", methods=["POST"])
    @login_required
    def chat_send():
        import asyncio
        from services.pi_agent_client import chat as pi_chat

        payload = request.get_json(silent=True) or {}
        message = (payload.get("message") or "").strip()
        user_id = payload.get("user_id")

        if not message:
            return jsonify({"error": "Leere Nachricht."}), 400
        if user_id not in {u["id"] for u in _chat_users()}:
            return jsonify({"error": "Unbekannter Nutzer."}), 400

        user = next(u for u in _chat_users() if u["id"] == user_id)
        user_name = user.get("full_name") or user.get("username") or "Athlet"

        try:
            reply = asyncio.run(pi_chat(user_id, user_name, message))
        except Exception as exc:
            # Rate limit and missing-key both surface as ValueError with a
            # message meant for the user; anything else is a real failure.
            logger.exception("Chat failed for user %s", user_id)
            return jsonify({"error": str(exc)}), 502

        return jsonify({"response": reply})

    # ─── Health check ─────────────────────────────────────────────────────────

    @app.route("/health")
    def health():
        return {"status": "ok", "service": "wodpilot-web"}, 200

    # ─── Internal Tools API (called by pi-agent microservice) ─────────────────

    def _require_internal_token():
        """Return 401 if the request doesn't carry the internal API token."""
        token = cfg.internal_api_token
        if not token:
            return None  # token check disabled – dev mode
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {token}":
            abort(401)

    @app.route("/api/tools/training-load")
    def tools_training_load():
        _require_internal_token()
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from services.garmin import get_training_load
        load = get_training_load(user_id)
        return jsonify({
            "atl": load.atl,
            "ctl": load.ctl,
            "tsb": load.tsb,
            "weekly_tss": load.weekly_tss,
            "run_km_14d": load.run_km_14d,
            "recommendation": load.recommendation,
        })

    @app.route("/api/tools/recent-activities")
    def tools_recent_activities():
        _require_internal_token()
        user_id = request.args.get("user_id", type=int)
        days = request.args.get("days", default=7, type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from services.garmin import get_recent_activities
        activities = get_recent_activities(user_id, days=min(days, 30))
        return jsonify(activities)

    @app.route("/api/tools/wods")
    def tools_wods():
        _require_internal_token()
        from services.scraper import get_todays_wods
        wods = get_todays_wods()
        if not wods:
            return jsonify({"message": "Keine WODs für heute verfügbar. Generiere ein individuelles Workout."})
        return jsonify(wods)

    @app.route("/api/tools/search-memory", methods=["POST"])
    def tools_search_memory():
        _require_internal_token()
        data = request.get_json() or {}
        user_id = data.get("user_id")
        query = data.get("query", "")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from memory.semantic import search_memory
        results = search_memory(user_id, query)
        if not results:
            return jsonify({"message": f"Keine Einträge zu '{query}' gefunden."})
        return jsonify(results)

    @app.route("/api/tools/search-episodes", methods=["POST"])
    def tools_search_episodes():
        _require_internal_token()
        data = request.get_json() or {}
        user_id = data.get("user_id")
        query = data.get("query", "")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from memory.episodic import search_episodes
        results = search_episodes(user_id, query)
        if not results:
            return jsonify({"message": f"Keine Episoden zu '{query}' gefunden."})
        return jsonify(results)

    @app.route("/api/tools/prs")
    def tools_prs():
        _require_internal_token()
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from memory.episodic import get_prs
        prs = get_prs(user_id)
        if not prs:
            return jsonify({"message": "Noch keine PRs gespeichert."})
        return jsonify(prs)

    @app.route("/api/tools/save-memory", methods=["POST"])
    def tools_save_memory():
        _require_internal_token()
        data = request.get_json() or {}
        user_id = data.get("user_id")
        key = data.get("key", "")
        value = data.get("value", "")
        category = data.get("category")
        if not user_id or not key:
            return jsonify({"error": "user_id, key required"}), 400
        from memory.semantic import save_memory
        save_memory(user_id, key, value, category)
        return jsonify({"message": f"Gespeichert: {key} = {value}"})

    @app.route("/api/tools/add-episode", methods=["POST"])
    def tools_add_episode():
        _require_internal_token()
        data = request.get_json() or {}
        user_id = data.get("user_id")
        content = data.get("content", "")
        category = data.get("category")
        metadata = data.get("metadata")
        if not user_id or not content:
            return jsonify({"error": "user_id, content required"}), 400
        from memory.episodic import add_episode
        add_episode(user_id, content, category, metadata)
        return jsonify({"message": f"Episode gespeichert: {content}"})

    @app.route("/api/tools/coaching-profile")
    def tools_coaching_profile():
        _require_internal_token()
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from memory.procedural import get_coaching_profile
        profile = get_coaching_profile(user_id)
        return jsonify(profile)

    @app.route("/api/tools/update-coaching-style", methods=["POST"])
    def tools_update_coaching_style():
        _require_internal_token()
        data = request.get_json() or {}
        user_id = data.get("user_id")
        coaching_style = data.get("coaching_style")
        notes = data.get("notes")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        from memory.procedural import update_coaching_style
        update_coaching_style(user_id, coaching_style=coaching_style, notes=notes)
        return jsonify({"message": f"Coaching-Stil aktualisiert: {coaching_style or 'unverändert'}"})

    @app.route("/api/tools/training-preferences", methods=["GET", "POST"])
    def tools_training_preferences():
        _require_internal_token()
        from services.planning import get_preferences, save_preferences

        if request.method == "POST":
            data = request.get_json() or {}
            user_id = data.get("user_id")
            text = (data.get("preferences_text") or "").strip()
            if not user_id or not text:
                return jsonify({"error": "user_id, preferences_text required"}), 400
            save_preferences(user_id, text)
            return jsonify({"message": "Trainingspräferenzen gespeichert."})

        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        text = get_preferences(user_id)
        if not text:
            return jsonify({"message": "Noch keine Präferenzen hinterlegt."})
        return jsonify({"preferences_text": text})

    @app.route("/api/tools/week-plan", methods=["GET", "POST"])
    def tools_week_plan():
        _require_internal_token()
        from services.planning import current_week_start, get_week_plan, save_week_plan

        if request.method == "POST":
            data = request.get_json() or {}
            user_id = data.get("user_id")
            week_start = data.get("week_start")
            sessions = data.get("sessions")
            if not user_id or not week_start:
                return jsonify({"error": "user_id, week_start required"}), 400
            if not isinstance(sessions, list) or not sessions:
                return jsonify({"error": "sessions must be a non-empty list"}), 400
            for s in sessions:
                if not all(s.get(k) for k in ("date", "title", "description")):
                    return jsonify({"error": "each session needs date, title, description"}), 400
            count = save_week_plan(user_id, week_start, sessions)
            return jsonify({"message": f"Wochenplan gespeichert: {count} Einheiten ab {week_start}."})

        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        week_start = request.args.get("week_start") or current_week_start().isoformat()
        plan = get_week_plan(user_id, week_start)
        if not plan:
            return jsonify({"message": f"Kein Wochenplan für die Woche ab {week_start} vorhanden."})
        return jsonify(plan)

    @app.route("/api/tools/session-result", methods=["POST"])
    def tools_session_result():
        _require_internal_token()
        from services.planning import log_session_result

        data = request.get_json() or {}
        user_id = data.get("user_id")
        session_id = data.get("session_id")
        session_date = data.get("date")
        status = data.get("status", "done")
        rpe = data.get("rpe")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        if not session_id and not session_date:
            return jsonify({"error": "session_id or date required"}), 400
        if status not in ("done", "skipped"):
            return jsonify({"error": "status must be 'done' or 'skipped'"}), 400
        if rpe is not None and not (isinstance(rpe, int) and 1 <= rpe <= 10):
            return jsonify({"error": "rpe must be an integer 1-10"}), 400
        result = log_session_result(
            user_id,
            session_id=session_id,
            session_date=session_date,
            status=status,
            result_text=data.get("result_text"),
            rpe=rpe,
            notes=data.get("notes"),
        )
        if result is None:
            return jsonify({"message": "Keine passende Einheit gefunden. Erst get_week_plan aufrufen und die Session-ID nutzen."})
        return jsonify({"message": f"Ergebnis gespeichert für '{result['title']}' am {result['date']}."})

    @app.route("/api/tools/issues", methods=["GET", "POST"])
    def tools_issues():
        _require_internal_token()
        from services.issues import KINDS, PRIORITIES, create_issue, list_issues

        if request.method == "POST":
            data = request.get_json() or {}
            user_id = data.get("user_id")
            title = (data.get("title") or "").strip()
            if not user_id or not title:
                return jsonify({"error": "user_id, title required"}), 400
            kind = data.get("kind") or "other"
            priority = data.get("priority") or "normal"
            if kind not in KINDS:
                return jsonify({"error": f"kind must be one of {', '.join(KINDS)}"}), 400
            if priority not in PRIORITIES:
                return jsonify({"error": f"priority must be one of {', '.join(PRIORITIES)}"}), 400
            issue = create_issue(
                user_id,
                title=title,
                body=data.get("body") or "",
                kind=kind,
                priority=priority,
            )
            return jsonify({
                "message": f"Issue #{issue['id']} angelegt: {issue['title']}",
                "issue_id": issue["id"],
            })

        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        issue_list = list_issues(status="open,in_progress", user_id=user_id, limit=20)
        if not issue_list:
            return jsonify({"message": "Keine offenen Issues von diesem Athleten."})
        return jsonify([
            {k: i[k] for k in ("id", "title", "kind", "priority", "status", "created_at")}
            for i in issue_list
        ])

    # ─── Athlete dashboard (magic-link auth, /me/...) ─────────────────────────

    from web.athlete import athlete_bp
    app.register_blueprint(athlete_bp)

    return app
