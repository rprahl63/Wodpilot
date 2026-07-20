import express, { type Request, type Response } from "express";
import { completeSimple, registerBuiltInApiProviders } from "@mariozechner/pi-ai";
import type { UserMessage } from "@mariozechner/pi-ai";
import { buildAgent, runAgent, SYSTEM_PROMPT } from "./agent.js";
import { buildRequestyModel, DEFAULT_MODEL, REQUESTY_BASE_URL } from "./requesty.js";
import type {
  AgentResponse,
  AnalyzeRequest,
  BriefingRequest,
  ChatRequest,
  PlanWeekRequest,
} from "./types.js";

registerBuiltInApiProviders();

const app = express();
app.use(express.json({ limit: "50mb" }));

const PORT = parseInt(process.env.PORT ?? "3001", 10);

const BRIEFING_MESSAGE =
  "Erstelle ein morgendliches Briefing für heute. " +
  "Prüfe meinen Trainingsstatus, hole die heutigen WODs und gib mir: " +
  "1. Meinen aktuellen Trainingsstatus (ATL/CTL/TSB kurz erklärt), " +
  "2. Empfehlung für das heutige Training (inkl. Skalierung), " +
  "3. Einen motivierenden Fokus-Punkt für heute.";

app.post("/chat", async (req: Request, res: Response) => {
  const { user_id, message, history, api_key, model }: ChatRequest = req.body;

  if (!user_id || !message || !api_key) {
    res.status(400).json({ error: "user_id, message, api_key are required" });
    return;
  }

  try {
    const agent = await buildAgent(user_id, api_key, model ?? DEFAULT_MODEL, history ?? []);
    const response = await runAgent(agent, message);
    res.json({ response } satisfies AgentResponse);
  } catch (err) {
    console.error("Chat error:", err);
    res.status(500).json({
      error: String(err),
      response: "Interner Fehler. Bitte versuche es erneut.",
    } satisfies AgentResponse);
  }
});

app.post("/briefing", async (req: Request, res: Response) => {
  const { user_id, api_key, model }: BriefingRequest = req.body;

  if (!user_id || !api_key) {
    res.status(400).json({ error: "user_id, api_key are required" });
    return;
  }

  try {
    const agent = await buildAgent(user_id, api_key, model ?? DEFAULT_MODEL, []);
    const response = await runAgent(agent, BRIEFING_MESSAGE);
    res.json({ response } satisfies AgentResponse);
  } catch (err) {
    console.error("Briefing error:", err);
    res.status(500).json({
      error: String(err),
      response: "Briefing fehlgeschlagen.",
    } satisfies AgentResponse);
  }
});

function planWeekMessage(weekStart: string, constraints?: string): string {
  const constraintBlock = constraints
    ? `\n\nDer Athlet hat für diese Woche mitgeteilt:\n"${constraints}"\nBerücksichtige das verbindlich – verschiebe oder streiche Einheiten entsprechend.`
    : "\n\nDer Athlet hat keine Rückmeldung gegeben. Plane allein anhand seiner Präferenzen und Trainingsdaten.";

  return (
    `Plane die Trainingswoche ab Montag, ${weekStart}.\n\n` +
    "Vorgehen:\n" +
    "1. Hole get_training_preferences für den gewünschten Wochenrhythmus.\n" +
    "2. Hole get_training_load und get_recent_activities (14 Tage), um die Belastung einzuschätzen.\n" +
    "3. Durchsuche das Memory nach Verletzungen und Zielen, die die Planung beeinflussen.\n" +
    constraintBlock +
    "\n\nSchreibe jede Einheit vollständig aus, so dass sie ohne Rückfrage ausführbar ist: " +
    "Warm-Up, Hauptteil mit konkreten Sätzen/Wiederholungen/Pace/Pausen (z. B. '6x400m @ 5k-Pace, 90s Pause'), Cool-Down.\n" +
    `Speichere den Plan anschließend mit save_week_plan (week_start=${weekStart}).\n` +
    "Antworte danach mit einer kurzen Übersicht der Woche für Telegram – ein Tag pro Zeile."
  );
}

app.post("/plan-week", async (req: Request, res: Response) => {
  const { user_id, api_key, model, constraints, week_start }: PlanWeekRequest = req.body;

  if (!user_id || !api_key || !week_start) {
    res.status(400).json({ error: "user_id, api_key, week_start are required" });
    return;
  }

  try {
    const agent = await buildAgent(user_id, api_key, model ?? DEFAULT_MODEL, []);
    const response = await runAgent(agent, planWeekMessage(week_start, constraints));
    res.json({ response } satisfies AgentResponse);
  } catch (err) {
    console.error("Plan week error:", err);
    res.status(500).json({
      error: String(err),
      response: "Wochenplanung fehlgeschlagen.",
    } satisfies AgentResponse);
  }
});

app.post("/analyze", async (req: Request, res: Response) => {
  const { user_id, message, media_base64, media_type, api_key, model }: AnalyzeRequest =
    req.body;

  if (!user_id || !media_base64 || !api_key) {
    res.status(400).json({ error: "user_id, media_base64, api_key are required" });
    return;
  }

  try {
    const llmModel = await buildRequestyModel(model ?? DEFAULT_MODEL, api_key);
    const prompt =
      message ||
      "Analysiere dieses Bild aus der Perspektive eines CrossFit Coaches. Gib konkretes Feedback.";

    const userMsg: UserMessage = {
      role: "user",
      content: [
        { type: "image", data: media_base64, mimeType: media_type },
        { type: "text", text: prompt },
      ],
      timestamp: Date.now(),
    };

    const result = await completeSimple(
      llmModel,
      { systemPrompt: SYSTEM_PROMPT, messages: [userMsg] },
      { apiKey: api_key }
    );

    const textContent = result.content.find((c) => c.type === "text");
    const response =
      textContent && textContent.type === "text"
        ? textContent.text
        : "Analyse fehlgeschlagen.";

    res.json({ response } satisfies AgentResponse);
  } catch (err) {
    console.error("Analyze error:", err);
    res.status(500).json({
      error: String(err),
      response: "Bild-Analyse fehlgeschlagen.",
    } satisfies AgentResponse);
  }
});

app.get("/models", async (req: Request, res: Response) => {
  const apiKey = req.header("x-api-key");
  if (!apiKey) {
    res.status(400).json({ error: "x-api-key header required" });
    return;
  }

  try {
    const upstream = await fetch(`${REQUESTY_BASE_URL}/models`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (!upstream.ok) {
      res.status(upstream.status).json({ error: `Requesty: HTTP ${upstream.status}` });
      return;
    }

    const body = (await upstream.json()) as { data: Record<string, unknown>[] };
    // Only tool-capable models: the coach is useless without data access.
    const models = body.data
      .filter((m) => m.supports_tool_calling)
      .map((m) => ({
        id: m.id,
        context_window: m.context_window,
        input_price: m.input_price,
        output_price: m.output_price,
        supports_vision: m.supports_vision ?? false,
        supports_reasoning: m.supports_reasoning ?? false,
      }))
      .sort((a, b) => String(a.id).localeCompare(String(b.id)));

    res.json({ models, default: DEFAULT_MODEL });
  } catch (err) {
    console.error("Model list error:", err);
    res.status(502).json({ error: String(err) });
  }
});

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: "wodpilot-pi-agent" });
});

app.listen(PORT, () => {
  console.log(`WODpilot pi-agent service running on port ${PORT}`);
});
