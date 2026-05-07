export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  user_id: number;
  user_name?: string;
  message: string;
  history?: HistoryMessage[];
  api_key: string;
  model?: string;
}

export interface BriefingRequest {
  user_id: number;
  user_name?: string;
  api_key: string;
  model?: string;
}

export interface AnalyzeRequest {
  user_id: number;
  user_name?: string;
  message?: string;
  media_base64: string;
  media_type: string;
  api_key: string;
  model?: string;
}

export interface AgentResponse {
  response: string;
  error?: string;
}
