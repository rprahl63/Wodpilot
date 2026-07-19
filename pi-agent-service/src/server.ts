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
