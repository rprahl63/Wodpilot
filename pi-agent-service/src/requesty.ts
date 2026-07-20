/**
 * Requesty router support.
 *
 * pi-ai's `getModel()` only knows its built-in catalogue, but a `Model` is a
 * plain data object — so we can point one at Requesty's OpenAI-compatible
 * endpoint instead. `Provider` is an open string type, which lets us tag these
 * as "requesty" and hand back the right key in `getApiKey`.
 */
import type { Model } from "@mariozechner/pi-ai";

export const REQUESTY_BASE_URL =
  process.env.REQUESTY_BASE_URL ?? "https://router.requesty.ai/v1";

export const DEFAULT_MODEL =
  process.env.DEFAULT_LLM_MODEL ?? "anthropic/claude-sonnet-4-5";

export const REQUESTY_PROVIDER = "requesty";

interface RequestyModel {
  id: string;
  description?: string;
  input_price?: number;
  output_price?: number;
  caching_price?: number;
  cached_price?: number;
  max_output_tokens?: number;
  context_window?: number;
  supports_vision?: boolean;
  supports_reasoning?: boolean;
  supports_tool_calling?: boolean;
  supports_web_search?: boolean;
}

/**
 * Model used for the web_search sub-call. Not every chat model can search;
 * override this when the athlete's own model lacks the capability.
 */
export const WEB_SEARCH_MODEL = process.env.WEB_SEARCH_MODEL ?? "";

const CATALOGUE_TTL_MS = 60 * 60 * 1000;
let catalogue: { fetchedAt: number; models: Map<string, RequestyModel> } | null = null;

async function loadCatalogue(apiKey: string): Promise<Map<string, RequestyModel>> {
  if (catalogue && Date.now() - catalogue.fetchedAt < CATALOGUE_TTL_MS) {
    return catalogue.models;
  }

  const res = await fetch(`${REQUESTY_BASE_URL}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  if (!res.ok) {
    throw new Error(`Requesty model catalogue: HTTP ${res.status}`);
  }

  const body = (await res.json()) as { data: RequestyModel[] };
  const models = new Map(body.data.map((m) => [m.id, m]));
  catalogue = { fetchedAt: Date.now(), models };
  return models;
}

/**
 * Requesty quotes prices per token; pi-ai's calculateCost() divides by a
 * million, so scale up to keep the reported cost honest.
 */
const perMillion = (price: number | undefined): number => (price ?? 0) * 1_000_000;

/**
 * Used when the catalogue is unreachable. Deliberately conservative: a wrong
 * maxTokens would truncate answers, and a wrong cost would misreport spend.
 */
function fallbackModel(modelId: string): Model<"openai-completions"> {
  return {
    id: modelId,
    name: modelId,
    api: "openai-completions",
    provider: REQUESTY_PROVIDER,
    baseUrl: REQUESTY_BASE_URL,
    reasoning: false,
    input: ["text", "image"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 200_000,
    maxTokens: 8_192,
  };
}

export async function buildRequestyModel(
  modelId: string,
  apiKey: string
): Promise<Model<"openai-completions">> {
  const id = modelId || DEFAULT_MODEL;

  let meta: RequestyModel | undefined;
  try {
    meta = (await loadCatalogue(apiKey)).get(id);
  } catch (err) {
    console.warn(`Requesty catalogue unavailable, using fallback metadata: ${err}`);
    return fallbackModel(id);
  }

  if (!meta) {
    console.warn(`Model "${id}" not in Requesty catalogue, using fallback metadata`);
    return fallbackModel(id);
  }

  return {
    id,
    name: id,
    api: "openai-completions",
    provider: REQUESTY_PROVIDER,
    baseUrl: REQUESTY_BASE_URL,
    reasoning: meta.supports_reasoning ?? false,
    input: meta.supports_vision ? ["text", "image"] : ["text"],
    cost: {
      input: perMillion(meta.input_price),
      output: perMillion(meta.output_price),
      cacheRead: perMillion(meta.cached_price),
      cacheWrite: perMillion(meta.caching_price),
    },
    contextWindow: meta.context_window ?? 200_000,
    maxTokens: meta.max_output_tokens ?? 8_192,
  };
}

/** Whether the model can run Requesty's server-side web search. */
export async function supportsWebSearch(modelId: string, apiKey: string): Promise<boolean> {
  try {
    const meta = (await loadCatalogue(apiKey)).get(modelId);
    return meta?.supports_web_search ?? false;
  } catch {
    return true; // don't block on a catalogue outage – the call itself will tell us
  }
}

/** Whether the model can call tools. Without that the coach has no data access. */
export async function supportsTools(modelId: string, apiKey: string): Promise<boolean> {
  try {
    const meta = (await loadCatalogue(apiKey)).get(modelId);
    return meta?.supports_tool_calling ?? false;
  } catch {
    return true; // don't block on a catalogue outage
  }
}
