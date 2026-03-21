"""
Pydantic AI tool definitions for the WODpilot coach agent.

All tools receive the user_id via RunContext dependencies.
The agent autonomously decides which tools to call and in what order.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext  # type: ignore

from services.garmin import get_training_load, get_recent_activities
from services.scraper import get_todays_wods
from memory.semantic import search_memory, save_memory, get_all_memories
from memory.episodic import search_episodes, add_episode, get_prs
from memory.procedural import get_coaching_profile, update_coaching_style

logger = logging.getLogger(__name__)


@dataclass
class CoachDeps:
    user_id: int
    user_name: str


# ─── Tool implementations ─────────────────────────────────────────────────────

async def tool_get_training_load(ctx: RunContext[CoachDeps]) -> str:
    """
    Get current ATL/CTL/TSB training load metrics and a recommendation.
    Always call this first when the athlete asks about training readiness.
    """
    load = get_training_load(ctx.deps.user_id)
    return json.dumps(
        {
            "atl": load.atl,
            "ctl": load.ctl,
            "tsb": load.tsb,
            "weekly_tss": load.weekly_tss,
            "run_km_14d": load.run_km_14d,
            "recommendation": load.recommendation,
        },
        ensure_ascii=False,
    )


async def tool_get_recent_activities(ctx: RunContext[CoachDeps], days: int = 7) -> str:
    """
    Get recent Garmin activities for the last N days.
    Use this to understand what the athlete has been doing recently.
    Returns activity type, duration, HR, distance, TSS.
    Warns if running volume > 50 km/14d.
    """
    activities = get_recent_activities(ctx.deps.user_id, days=min(days, 30))
    return json.dumps(activities, ensure_ascii=False, default=str)


async def tool_get_todays_wods(ctx: RunContext[CoachDeps]) -> str:
    """
    Get today's WODs from all configured CrossFit boxes.
    Use this when generating a training recommendation for today.
    """
    wods = get_todays_wods()
    if not wods:
        return "Keine WODs für heute verfügbar. Generiere ein individuelles Workout."
    return json.dumps(wods, ensure_ascii=False, default=str)


async def tool_search_memory(ctx: RunContext[CoachDeps], query: str) -> str:
    """
    Search the athlete's semantic memory (PRs, injuries, goals, preferences).
    Use this to recall relevant facts about the athlete.
    Example queries: 'shoulder injury', 'back squat PR', 'goals 2025'
    """
    results = search_memory(ctx.deps.user_id, query)
    if not results:
        return f"Keine Einträge zu '{query}' gefunden."
    return json.dumps(results, ensure_ascii=False)


async def tool_search_episodes(ctx: RunContext[CoachDeps], query: str) -> str:
    """
    Search episodic memory for specific events (PRs, achievements, injuries).
    Use this when the athlete references past performances.
    """
    results = search_episodes(ctx.deps.user_id, query)
    if not results:
        return f"Keine Episoden zu '{query}' gefunden."
    return json.dumps(results, ensure_ascii=False, default=str)


async def tool_get_all_prs(ctx: RunContext[CoachDeps]) -> str:
    """
    Get all Personal Records for the athlete.
    Use this when discussing performance history or setting new training goals.
    """
    prs = get_prs(ctx.deps.user_id)
    if not prs:
        return "Noch keine PRs gespeichert."
    return json.dumps(prs, ensure_ascii=False, default=str)


async def tool_save_memory(
    ctx: RunContext[CoachDeps],
    key: str,
    value: str,
    category: Optional[str] = None,
) -> str:
    """
    Save an important fact to semantic memory.
    Use this when learning something important about the athlete:
    injuries, PRs, goals, preferences, scaling levels.
    Categories: 'injury', 'pr', 'goal', 'preference', 'scaling'
    """
    save_memory(ctx.deps.user_id, key, value, category)
    return f"Gespeichert: {key} = {value}"


async def tool_add_episode(
    ctx: RunContext[CoachDeps],
    content: str,
    category: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Add an episodic memory entry for a specific event.
    Use this for: PRs, injuries, achievements, notable workouts.
    Categories: 'pr', 'injury', 'achievement', 'scaling', 'wod_result'
    Metadata example: {"exercise": "deadlift", "weight_kg": 145, "reps": 1}
    """
    add_episode(ctx.deps.user_id, content, category, metadata)
    return f"Episode gespeichert: {content}"


async def tool_get_coaching_profile(ctx: RunContext[CoachDeps]) -> str:
    """
    Get the athlete's coaching style profile.
    Use this to adapt communication style (direct/supportive/technical/balanced).
    """
    profile = get_coaching_profile(ctx.deps.user_id)
    return json.dumps(profile, ensure_ascii=False)


async def tool_update_coaching_style(
    ctx: RunContext[CoachDeps],
    coaching_style: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Update the coaching style based on athlete feedback.
    Valid styles: 'direct', 'supportive', 'technical', 'balanced'
    Use 'notes' to remember specific communication preferences.
    """
    update_coaching_style(
        ctx.deps.user_id,
        coaching_style=coaching_style,
        notes=notes,
    )
    return f"Coaching-Stil aktualisiert: {coaching_style or 'unverändert'}"
