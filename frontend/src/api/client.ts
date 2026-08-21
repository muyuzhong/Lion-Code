import { ModelChoice, ServerStatus, SessionSummary, SkillItem } from '../types';

const API_BASE = '/api';

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

export async function fetchStatus(): Promise<ServerStatus> {
  const res = await fetch(`${API_BASE}/status`);
  const data = await res.json();
  return {
    sessionId: data.session_id,
    model: data.model,
    providerName: data.provider_name,
    permissionMode: data.permission_mode,
    apiConfigured: data.api_configured,
    cwd: data.cwd,
    thinkingLevel: data.thinking_level,
    availableThinkingLevels: data.available_thinking_levels || [],
    inputTokens: data.input_tokens || 0,
    outputTokens: data.output_tokens || 0,
    isRunning: data.is_running || false,
  };
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${API_BASE}/sessions`);
  return res.json();
}

export async function resumeSession(sessionId: string): Promise<{ success: boolean; session_id: string }> {
  const res = await fetch(`${API_BASE}/sessions/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });
  return res.json();
}

export async function createNewSession(): Promise<{ success: boolean; session_id: string }> {
  const res = await fetch(`${API_BASE}/sessions/new`, {
    method: 'POST',
  });
  return res.json();
}

export async function fetchModels(): Promise<ModelChoice[]> {
  const res = await fetch(`${API_BASE}/models`);
  return res.json();
}

export async function fetchSkills(): Promise<SkillItem[]> {
  const res = await fetch(`${API_BASE}/skills`);
  return res.json();
}

export async function setThinkingLevel(level: string): Promise<{ thinking_level: string }> {
  const res = await fetch(`${API_BASE}/thinking`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  });
  return res.json();
}

export async function configureProvider(config: {
  model?: string;
  api_key?: string;
  provider?: 'openai' | 'anthropic';
  base_url?: string;
}): Promise<{ success: boolean; model: string; provider: string }> {
  const res = await fetch(`${API_BASE}/config/provider`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return res.json();
}
