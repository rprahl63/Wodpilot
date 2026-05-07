import { Agent } from "@mariozechner/pi-agent-core";
import { getModel, registerBuiltInApiProviders } from "@mariozechner/pi-ai";
import type {
  AssistantMessage,
  Message,
  UserMessage,
} from "@mariozechner/pi-ai";
import { createTools } from "./tools.js";
import type { HistoryMessage } from "./types.js";

registerBuiltInApiProviders();

const DEFAULT_MODEL = "claude-sonnet-4-20250514";

export const SYSTEM_PROMPT = `Du bist WODpilot – ein KI-gestützter CrossFit Remote Coach.

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
- Emoji sparsam einsetzen.`;

function getAnthropicModel(modelId: string) {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return getModel("anthropic", modelId as any);
  } catch {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return getModel("anthropic", DEFAULT_MODEL as any);
  }
}

function convertHistory(history: HistoryMessage[], modelId: string): Message[] {
  return history.map((msg, i): Message => {
    const ts = Date.now() - (history.length - i) * 1000;
    if (msg.role === "user") {
      return { role: "user", content: msg.content, timestamp: ts } satisfies UserMessage;
    }
    return {
      role: "assistant",
      content: [{ type: "text", text: msg.content }],
      api: "anthropic-messages",
      provider: "anthropic",
      model: modelId,
      usage: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
      },
      stopReason: "stop",
      timestamp: ts,
    } satisfies AssistantMessage;
  });
}

export function buildAgent(
  userId: number,
  apiKey: string,
  modelName: string,
  history: HistoryMessage[] = []
): Agent {
  const model = getAnthropicModel(modelName || DEFAULT_MODEL);
  const tools = createTools(userId);
  const messages = convertHistory(history, modelName || DEFAULT_MODEL);

  return new Agent({
    initialState: {
      model,
      systemPrompt: SYSTEM_PROMPT,
      tools,
      messages,
    },
    convertToLlm: (msgs) =>
      msgs.filter(
        (m): m is Message =>
          (m as Message).role === "user" ||
          (m as Message).role === "assistant" ||
          (m as Message).role === "toolResult"
      ),
    getApiKey: (provider) => (provider === "anthropic" ? apiKey : undefined),
  });
}

export async function runAgent(agent: Agent, message: string): Promise<string> {
  await agent.prompt(message);
  await agent.waitForIdle();

  const messages = agent.state.messages;
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as Message;
    if (msg.role === "assistant") {
      const am = msg as AssistantMessage;
      const text = am.content.find((c) => c.type === "text");
      if (text && text.type === "text") return text.text;
    }
  }
  return "Keine Antwort erhalten.";
}
