export type Role = 'user' | 'assistant' | 'system';

export interface ToolCallItem {
  id: string;
  toolName: string;
  parameters?: Record<string, any> | string;
  result?: string;
  isError?: boolean;
  status: 'running' | 'success' | 'error';
  timestamp?: number;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  thinking?: string;
  isThinkingActive?: boolean;
  tools?: ToolCallItem[];
  timestamp: number;
}

export interface ConfirmRequest {
  requestId: string;
  message: string;
}

export interface PlanApprovalRequest {
  requestId: string;
  plan: string;
}

export interface ServerStatus {
  sessionId: string;
  model: string;
  providerName: string;
  permissionMode: string;
  apiConfigured: boolean;
  cwd: string;
  thinkingLevel: string;
  availableThinkingLevels: string[];
  inputTokens: number;
  outputTokens: number;
  isRunning: boolean;
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

export interface SkillItem {
  name: string;
  description?: string;
}
