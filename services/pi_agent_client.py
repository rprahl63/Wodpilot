"""
HTTP client for the pi-agent microservice.

Replaces the Pydantic AI agent calls in bot/handlers.py.
The pi-agent service (Node.js) handles LLM orchestration and tool calling.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from config import get_config
from db.client import get_db
from memory.working import add_message, get_conversation_history
from utils.crypto import decrypt

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(120.0)


def _get_user_api_key(user_id: int) -> tuple[str, str]:
    """Return (decrypted_api_key, model_name) for a user."""
    db = get_db()
    row = (
        db.table("users")
        .select("llm_api_key_enc,llm_model")
        .eq("id", user_id)
        .single()
        .execute()
    ).data
    if not row or not row.get("llm_api_key_enc"):
        raise ValueError(
            "Kein API-Key hinterlegt. Bitte unter /settings deinen Anthropic API-Key eintragen."
        )
    api_key = decrypt(row["llm_api_key_enc"])
    model = row.get("llm_model") or get_config().default_llm_model
    return api_key, model


def _check_and_increment_rate_limit(user_id: int) -> None:
    """Raise if daily API call limit exceeded."""
    from datetime import date

    db = get_db()
    today = date.today().isoformat()
    row = (
        db.table("users")
        .select("api_calls_today,api_calls_reset_at")
        .eq("id", user_id)
        .single()
        .execute()
    ).data

    if row:
        reset_date = str(row.get("api_calls_reset_at", ""))
        if reset_date != today:
            db.table("users").update(
                {"api_calls_today": 1, "api_calls_reset_at": today}
            ).eq("id", user_id).execute()
            return
        calls = row.get("api_calls_today", 0) or 0
        max_calls = get_config().max_api_calls_per_day
        if calls >= max_calls:
            raise ValueError(
                f"Tägliches Limit von {max_calls} API-Aufrufen erreicht. Morgen wieder verfügbar."
            )
        db.table("users").update({"api_calls_today": calls + 1}).eq("id", user_id).execute()


def _build_history(user_id: int) -> list[dict[str, Any]]:
    """Fetch recent conversation history as a list of {role, content} dicts."""
    return get_conversation_history(user_id)


async def chat(user_id: int, user_name: str, message: str) -> str:
    """Send a message to the pi-agent service and return the response."""
    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)
    history = _build_history(user_id)

    add_message(user_id, "user", message)

    cfg = get_config()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{cfg.pi_agent_url}/chat",
            json={
                "user_id": user_id,
                "user_name": user_name,
                "message": message,
                "history": history,
                "api_key": api_key,
                "model": model,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    response = data.get("response", "Keine Antwort erhalten.")
    add_message(user_id, "assistant", response)
    return response


async def analyze_image(
    user_id: int, user_name: str, image_bytes: bytes, caption: str = ""
) -> str:
    """Send an image to the pi-agent service for analysis."""
    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)

    image_b64 = base64.standard_b64encode(image_bytes).decode()
    prompt = caption or "Analysiere dieses Bild aus der Perspektive eines CrossFit Coaches."

    cfg = get_config()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{cfg.pi_agent_url}/analyze",
            json={
                "user_id": user_id,
                "user_name": user_name,
                "message": prompt,
                "media_base64": image_b64,
                "media_type": "image/jpeg",
                "api_key": api_key,
                "model": model,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    result_text = data.get("response", "Analyse fehlgeschlagen.")
    add_message(user_id, "user", f"[Bild] {caption}")
    add_message(user_id, "assistant", result_text)
    return result_text


async def analyze_video(
    user_id: int, user_name: str, video_path: str, caption: str = ""
) -> str:
    """Extract frames from video and send to pi-agent for analysis."""
    import subprocess
    import tempfile
    from pathlib import Path

    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)

    frames_dir = tempfile.mkdtemp()
    ffmpeg = get_config().ffmpeg_path
    cmd = [
        ffmpeg, "-i", video_path,
        "-vf", "select='not(mod(n\\,floor(t*25/4)))',scale=640:-1",
        "-vsync", "0",
        "-frames:v", "4",
        f"{frames_dir}/frame_%02d.jpg",
        "-y",
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except Exception as exc:
        logger.error("ffmpeg failed: %s", exc)
        return "Video-Analyse fehlgeschlagen – konnte keine Frames extrahieren."

    frame_files = sorted(Path(frames_dir).glob("frame_*.jpg"))
    if not frame_files:
        return "Keine Frames aus Video extrahiert."

    # Send first frame for analysis (simplify: single representative frame)
    frame_bytes = frame_files[0].read_bytes()
    prompt = caption or "Analysiere die Bewegungsausführung in diesen Video-Frames. Gib konkretes Coaching-Feedback."

    result_text = await analyze_image(user_id, user_name, frame_bytes, prompt)
    add_message(user_id, "user", f"[Video] {caption}")
    add_message(user_id, "assistant", result_text)
    return result_text


async def generate_morning_briefing(user_id: int, user_name: str) -> str:
    """Generate a personalized morning briefing via the pi-agent service."""
    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)

    cfg = get_config()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{cfg.pi_agent_url}/briefing",
            json={
                "user_id": user_id,
                "user_name": user_name,
                "api_key": api_key,
                "model": model,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    response = data.get("response", "Briefing fehlgeschlagen.")
    add_message(user_id, "assistant", response)
    return response


async def generate_week_plan(
    user_id: int,
    user_name: str,
    constraints: str | None = None,
    plan_id: int | None = None,
    week_start: str | None = None,
) -> str:
    """
    Plan the training week via the pi-agent service.

    The caller must have claimed the plan row (see planning.claim_planning) so
    that a user reply and the fallback job can never plan the same week twice.
    The agent persists the sessions itself through the save_week_plan tool;
    afterwards we verify that sessions actually landed in the database, so a
    chatty answer without a stored plan is reported as a failure instead of
    silently leaving the week empty.
    """
    from services.planning import get_week_plan, set_plan_failed, upcoming_week_start

    ws = week_start or upcoming_week_start().isoformat()

    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)

    cfg = get_config()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{cfg.pi_agent_url}/plan-week",
                json={
                    "user_id": user_id,
                    "user_name": user_name,
                    "api_key": api_key,
                    "model": model,
                    "constraints": constraints,
                    "week_start": ws,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Week planning failed for user %s", user_id)
        if plan_id is not None:
            set_plan_failed(plan_id)
        raise

    plan = get_week_plan(user_id, ws)
    if not plan or not plan.get("sessions"):
        logger.error("Agent returned without storing sessions for user %s", user_id)
        if plan_id is not None:
            set_plan_failed(plan_id)
        return (
            "Die Wochenplanung hat leider nicht geklappt – es wurden keine Einheiten "
            "gespeichert. Schreib mir kurz, dann versuche ich es nochmal."
        )

    response = data.get("response", "Wochenplan erstellt.")
    add_message(user_id, "assistant", response)
    return response
