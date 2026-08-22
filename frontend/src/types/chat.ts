export interface ToolCallItem {
  id: string;
  toolName: string;
  args?: Record<string, unknown> | string;
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
  error?: string;
  isStreaming?: boolean;
  createdAt?: string | null;
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

// 对应后端 SkillItem（models.py）：description 可缺失
export interface SkillItem {
  name: string;
  description?: string | null;
}

export interface ConfirmRequest {
  requestId: string;
  message: string;
}

export interface PlanApprovalRequest {
  requestId: string;
  plan: string;
}
