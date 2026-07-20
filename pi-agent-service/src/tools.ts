import { Type } from "typebox";
import type { AgentTool, AgentToolResult } from "@mariozechner/pi-agent-core";

const PYTHON_API = process.env.PYTHON_API_URL ?? "http://web:8080";
const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function makeHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${INTERNAL_TOKEN}`,
  };
}

function textResult(text: string): AgentToolResult<Record<string, never>> {
  return { content: [{ type: "text", text }], details: {} };
}

async function apiGet(path: string): Promise<string> {
  const res = await fetch(`${PYTHON_API}${path}`, { headers: makeHeaders() });
  if (!res.ok) throw new Error(`Tools API ${path} returned ${res.status}`);
  return res.text();
}

async function apiPost(path: string, body: unknown): Promise<string> {
  const res = await fetch(`${PYTHON_API}${path}`, {
    method: "POST",
    headers: makeHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Tools API ${path} returned ${res.status}`);
  return res.text();
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function createTools(userId: number): AgentTool<any>[] {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return [
    {
      name: "get_training_load",
      label: "Get Training Load",
      description:
        "Get current ATL/CTL/TSB training load metrics and a recommendation. Always call this first when the athlete asks about training readiness.",
      parameters: Type.Object({}),
      execute: async () => {
        const text = await apiGet(`/api/tools/training-load?user_id=${userId}`);
        return textResult(text);
      },
    },
    {
      name: "get_recent_activities",
      label: "Get Recent Activities",
      description:
        "Get recent Garmin activities for the last N days. Returns activity type, duration, HR, distance, TSS. Use to understand what the athlete has been doing.",
      parameters: Type.Object({
        days: Type.Optional(
          Type.Number({ description: "Number of days to look back (max 30)", default: 7 })
        ),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { days?: number };
        const days = Math.min(p.days ?? 7, 30);
        const text = await apiGet(
          `/api/tools/recent-activities?user_id=${userId}&days=${days}`
        );
        return textResult(text);
      },
    },
    {
      name: "get_todays_wods",
      label: "Get Today's WODs",
      description:
        "Get today's WODs from all configured CrossFit boxes. Use when generating a training recommendation for today.",
      parameters: Type.Object({}),
      execute: async () => {
        const text = await apiGet(`/api/tools/wods`);
        return textResult(text);
      },
    },
    {
      name: "search_memory",
      label: "Search Semantic Memory",
      description:
        "Search the athlete's semantic memory (PRs, injuries, goals, preferences). Example queries: 'shoulder injury', 'back squat PR', 'goals 2025'",
      parameters: Type.Object({
        query: Type.String({ description: "Search query" }),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { query: string };
        const text = await apiPost(`/api/tools/search-memory`, {
          user_id: userId,
          query: p.query,
        });
        return textResult(text);
      },
    },
    {
      name: "search_episodes",
      label: "Search Episodic Memory",
      description:
        "Search episodic memory for specific events (PRs, achievements, injuries). Use when athlete references past performances.",
      parameters: Type.Object({
        query: Type.String({ description: "Search query" }),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { query: string };
        const text = await apiPost(`/api/tools/search-episodes`, {
          user_id: userId,
          query: p.query,
        });
        return textResult(text);
      },
    },
    {
      name: "get_all_prs",
      label: "Get All PRs",
      description:
        "Get all Personal Records for the athlete. Use when discussing performance history or setting new training goals.",
      parameters: Type.Object({}),
      execute: async () => {
        const text = await apiGet(`/api/tools/prs?user_id=${userId}`);
        return textResult(text);
      },
    },
    {
      name: "save_memory",
      label: "Save Memory",
      description:
        "Save an important fact to semantic memory. Use when learning something important: injuries, PRs, goals, preferences, scaling levels. Categories: 'injury', 'pr', 'goal', 'preference', 'scaling'",
      parameters: Type.Object({
        key: Type.String({ description: "Memory key" }),
        value: Type.String({ description: "Memory value" }),
        category: Type.Optional(
          Type.String({ description: "Category: injury, pr, goal, preference, scaling" })
        ),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { key: string; value: string; category?: string };
        const text = await apiPost(`/api/tools/save-memory`, {
          user_id: userId,
          key: p.key,
          value: p.value,
          category: p.category,
        });
        return textResult(text);
      },
    },
    {
      name: "add_episode",
      label: "Add Episode",
      description:
        "Add an episodic memory entry for a specific event. Use for PRs, injuries, achievements, notable workouts. Categories: 'pr', 'injury', 'achievement', 'scaling', 'wod_result'",
      parameters: Type.Object({
        content: Type.String({ description: "Episode content" }),
        category: Type.Optional(
          Type.String({
            description: "Category: pr, injury, achievement, scaling, wod_result",
          })
        ),
        metadata: Type.Optional(
          Type.Record(Type.String(), Type.Unknown(), {
            description: "Optional metadata e.g. {exercise: 'deadlift', weight_kg: 145}",
          })
        ),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { content: string; category?: string; metadata?: Record<string, unknown> };
        const text = await apiPost(`/api/tools/add-episode`, {
          user_id: userId,
          content: p.content,
          category: p.category,
          metadata: p.metadata,
        });
        return textResult(text);
      },
    },
    {
      name: "get_coaching_profile",
      label: "Get Coaching Profile",
      description:
        "Get the athlete's coaching style profile. Use to adapt communication style (direct/supportive/technical/balanced).",
      parameters: Type.Object({}),
      execute: async () => {
        const text = await apiGet(
          `/api/tools/coaching-profile?user_id=${userId}`
        );
        return textResult(text);
      },
    },
    {
      name: "update_coaching_style",
      label: "Update Coaching Style",
      description:
        "Update the coaching style based on athlete feedback. Valid styles: 'direct', 'supportive', 'technical', 'balanced'",
      parameters: Type.Object({
        coaching_style: Type.Optional(
          Type.String({ description: "Style: direct, supportive, technical, balanced" })
        ),
        notes: Type.Optional(
          Type.String({ description: "Specific communication preferences" })
        ),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { coaching_style?: string; notes?: string };
        const text = await apiPost(`/api/tools/update-coaching-style`, {
          user_id: userId,
          coaching_style: p.coaching_style,
          notes: p.notes,
        });
        return textResult(text);
      },
    },
    {
      name: "get_training_preferences",
      label: "Get Training Preferences",
      description:
        "Get the athlete's free-text training preferences (weekly rhythm, preferred session types, locations). Always call this before planning a week.",
      parameters: Type.Object({}),
      execute: async () => {
        const text = await apiGet(
          `/api/tools/training-preferences?user_id=${userId}`
        );
        return textResult(text);
      },
    },
    {
      name: "save_training_preferences",
      label: "Save Training Preferences",
      description:
        "Overwrite the athlete's training preferences. Use when the athlete describes a lasting change to their weekly training rhythm (not for one-off scheduling constraints).",
      parameters: Type.Object({
        preferences_text: Type.String({
          description: "Complete new preferences text, e.g. '1x/Woche Intervalle auf der 400m Bahn, 2x Laufen, 2x Functional Strength in der Box mit WOD'",
        }),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { preferences_text: string };
        const text = await apiPost(`/api/tools/training-preferences`, {
          user_id: userId,
          preferences_text: p.preferences_text,
        });
        return textResult(text);
      },
    },
    {
      name: "get_week_plan",
      label: "Get Week Plan",
      description:
        "Get the athlete's training plan for a week including every session with its id, date, title, description, status and logged result. Call this before discussing today's training and before logging a result (you need the session id).",
      parameters: Type.Object({
        week_start: Type.Optional(
          Type.String({
            description: "Monday of the week as YYYY-MM-DD. Defaults to the current week.",
          })
        ),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as { week_start?: string };
        const qs = p.week_start ? `&week_start=${p.week_start}` : "";
        const text = await apiGet(`/api/tools/week-plan?user_id=${userId}${qs}`);
        return textResult(text);
      },
    },
    {
      name: "save_week_plan",
      label: "Save Week Plan",
      description:
        "Store the training sessions for a week. Replaces any existing sessions for that week. Every session must be fully written out so the athlete can execute it without asking back.",
      parameters: Type.Object({
        week_start: Type.String({
          description: "Monday of the planned week as YYYY-MM-DD",
        }),
        sessions: Type.Array(
          Type.Object({
            date: Type.String({ description: "Session date as YYYY-MM-DD" }),
            title: Type.String({ description: "Short title, e.g. 'Intervalle 6x400m'" }),
            session_type: Type.Optional(
              Type.String({
                description: "One of: intervals, run, strength, wod, mobility, rest",
              })
            ),
            description: Type.String({
              description:
                "Full session: warm-up, main part with sets/reps/pace/rest, cool-down. Multi-line.",
            }),
            position: Type.Optional(
              Type.Number({ description: "Order within the day, starting at 0" })
            ),
          }),
          { description: "All sessions of the week, in chronological order" }
        ),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as {
          week_start: string;
          sessions: Record<string, unknown>[];
        };
        const text = await apiPost(`/api/tools/week-plan`, {
          user_id: userId,
          week_start: p.week_start,
          sessions: p.sessions,
        });
        return textResult(text);
      },
    },
    {
      name: "log_session_result",
      label: "Log Session Result",
      description:
        "Log the athlete's result for a planned session. Call get_week_plan first to find the matching session id. Use when the athlete reports a completed or skipped workout in chat.",
      parameters: Type.Object({
        session_id: Type.Optional(
          Type.Number({ description: "Session id from get_week_plan (preferred)" })
        ),
        date: Type.Optional(
          Type.String({
            description: "YYYY-MM-DD, only as a fallback when no session id is known",
          })
        ),
        status: Type.Optional(
          Type.String({ description: "'done' or 'skipped' (default: done)" })
        ),
        result_text: Type.Optional(
          Type.String({ description: "Result, e.g. '6x400m, Schnitt 1:31'" })
        ),
        rpe: Type.Optional(
          Type.Number({ description: "Perceived exertion 1-10" })
        ),
        notes: Type.Optional(Type.String({ description: "Additional notes" })),
      }),
      execute: async (_id: string, params: unknown) => {
        const p = params as {
          session_id?: number;
          date?: string;
          status?: string;
          result_text?: string;
          rpe?: number;
          notes?: string;
        };
        const text = await apiPost(`/api/tools/session-result`, {
          user_id: userId,
          session_id: p.session_id,
          date: p.date,
          status: p.status ?? "done",
          result_text: p.result_text,
          rpe: p.rpe,
          notes: p.notes,
        });
        return textResult(text);
      },
    },
  ];
}
