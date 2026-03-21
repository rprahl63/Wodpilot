"""
WODpilot Coach Agent – built with Pydantic AI.

The agent uses BYOK: every user's LLM API key is fetched from the DB.
Tools are called autonomously – no hardcoded context injection.
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent  # type: ignore
from pydantic_ai.models.anthropic import AnthropicModel  # type: ignore

from agent.tools import (
    CoachDeps,
    tool_get_training_load,
    tool_get_recent_activities,
    tool_get_todays_wods,
    tool_search_memory,
    tool_search_episodes,
    tool_get_all_prs,
    tool_save_memory,
    tool_add_episode,
    tool_get_coaching_profile,
    tool_update_coaching_style,
)
from config import get_config
from db.client import get_db
from memory.working import get_conversation_history, add_message
from utils.crypto import decrypt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du bist WODpilot – ein KI-gestützter CrossFit Remote Coach.

Deine Aufgabe ist es, Athleten individuell, kontextbewusst und kontinuierlich zu coachen.
Du kennst ihre Trainingsbelastung, Geschichte, PRs, Verletzungen und Ziele.

## Dein Vorgehen
1. Nutze deine Tools, um relevante Daten zu sammeln, bevor du antwortest.
2. Passe Empfehlungen immer an den aktuellen Trainingsstatus des Athleten an.
3. Speichere wichtige neue Informationen in das Memory-System.
4. Kommuniziere im Stil des Athletes (direct/supportive/technical/balanced).
5. Sei konkret: nenne Gewichte, Reps, Zeiten – keine vagen Aussagen.

## Wichtige Regeln
- Du bist kein Arzt. Bei Verletzungen: "Konsultiere einen Arzt oder Physiotherapeuten."
- Erkenne PRs und feiere sie – speichere sie in Episodic Memory.
- Wenn TSB < -10: Intensität reduzieren, nicht ignorieren.
- Bei Laufbelastung > 50km/14d: Unterkörper im WOD entlasten.
- YouTube Tutorial Links: Gib optimierte YouTube-Suchlinks als https://www.youtube.com/results?search_query=... aus.

## Format
- Kurze, prägnante Antworten – kein unnötiger Fülltext.
- Strukturierte Listen für Workouts (Warm-Up, WOD, Cool-Down).
- Emoji sparsam einsetzen.
"""


def _build_agent(api_key: str, model: str) -> Agent:
    """Build a fresh Pydantic AI agent for a given API key."""
    llm = AnthropicModel(model, api_key=api_key)
    agent: Agent[CoachDeps, str] = Agent(
        llm,
        system_prompt=_SYSTEM_PROMPT,
        deps_type=CoachDeps,
    )

    # Register all tools
    agent.tool(tool_get_training_load)
    agent.tool(tool_get_recent_activities)
    agent.tool(tool_get_todays_wods)
    agent.tool(tool_search_memory)
    agent.tool(tool_search_episodes)
    agent.tool(tool_get_all_prs)
    agent.tool(tool_save_memory)
    agent.tool(tool_add_episode)
    agent.tool(tool_get_coaching_profile)
    agent.tool(tool_update_coaching_style)

    return agent


def _get_user_api_key(user_id: int) -> tuple[str, str]:
    """Return (decrypted_api_key, model) for a user. Raises if not set."""
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
    db = get_db()
    from datetime import date
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
            # New day – reset counter
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


async def chat(user_id: int, user_name: str, message: str) -> str:
    """
    Main entry point for a user message.
    Fetches conversation history, runs the agent, persists messages.
    """
    # Rate limiting
    _check_and_increment_rate_limit(user_id)

    # BYOK
    api_key, model = _get_user_api_key(user_id)
    agent = _build_agent(api_key, model)

    deps = CoachDeps(user_id=user_id, user_name=user_name)

    # Build message history for context
    history = get_conversation_history(user_id)

    # Persist user message
    add_message(user_id, "user", message)

    # Run agent
    result = await agent.run(
        message,
        message_history=history,
        deps=deps,
    )
    response = result.output

    # Persist assistant response
    add_message(user_id, "assistant", response)

    return response


async def analyze_image(user_id: int, user_name: str, image_bytes: bytes, caption: str = "") -> str:
    """Analyze an image (board photo, exercise photo) via Claude Vision."""
    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)

    import anthropic  # type: ignore
    import base64

    client = anthropic.Anthropic(api_key=api_key)
    image_b64 = base64.standard_b64encode(image_bytes).decode()

    prompt = caption if caption else "Analysiere dieses Bild aus der Perspektive eines CrossFit Coaches."

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        system=_SYSTEM_PROMPT,
    )
    result_text = response.content[0].text

    add_message(user_id, "user", f"[Bild] {caption}")
    add_message(user_id, "assistant", result_text)
    return result_text


async def analyze_video(user_id: int, user_name: str, video_path: str, caption: str = "") -> str:
    """Extract frames from video via ffmpeg and analyze via Claude Vision."""
    import subprocess
    import base64

    _check_and_increment_rate_limit(user_id)
    api_key, model = _get_user_api_key(user_id)

    # Extract 4 frames evenly spaced
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

    import anthropic  # type: ignore
    client = anthropic.Anthropic(api_key=api_key)

    content: list = []
    for f in frame_files[:4]:
        img_b64 = base64.standard_b64encode(f.read_bytes()).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
        })
    prompt = caption or "Analysiere die Bewegungsausführung in diesen Video-Frames. Gib konkretes Coaching-Feedback."
    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
        system=_SYSTEM_PROMPT,
    )
    result_text = response.content[0].text

    add_message(user_id, "user", f"[Video] {caption}")
    add_message(user_id, "assistant", result_text)
    return result_text


async def generate_morning_briefing(user_id: int, user_name: str) -> str:
    """Generate a personalized morning briefing for the athlete."""
    message = (
        "Erstelle ein morgendliches Briefing für heute. "
        "Prüfe meinen Trainingsstatus, hole die heutigen WODs und gib mir: "
        "1. Meinen aktuellen Trainingsstatus (ATL/CTL/TSB kurz erklärt), "
        "2. Empfehlung für das heutige Training (inkl. Skalierung), "
        "3. Einen motivierenden Fokus-Punkt für heute."
    )
    return await chat(user_id, user_name, message)
