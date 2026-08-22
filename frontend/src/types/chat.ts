export interface ToolCallItem {
  id: string;
  toolName: string;
  args?: any;
  status: "running" | "completed" | "error";
  result?: string;
  expanded?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  reasoningDuration?: number;
  tools?: ToolCallItem[];
  isStreaming?: boolean;
  createdAt: string;
}

export interface ServerStatus {
  session_id: string;
  model: string;
  provider_name: string;
  permission_mode: string;
  api_configured: boolean;
  cwd: string;
  thinking_level: string;
  available_thinking_levels: string[];
  input_tokens: number;
  output_tokens: number;
  is_running: boolean;
}

export interface SessionSummary {
  id: string;
  startTime?: string;
  messageCount: number;
  cwd?: string;
}

export interface ModelChoice {
  provider_name: string;
  model: string;
}

export interface ConfirmRequest {
  request_id: string;
  message: string;
}

export interface PlanApprovalRequest {
  request_id: string;
  plan: string;
}
