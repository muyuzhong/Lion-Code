import { ChatMessage, ModelChoice, ServerStatus, SessionSummary } from "@/types/chat";

const API_BASE = "";

export async function fetchStatus(): Promise<ServerStatus> {
  const res = await fetch(`${API_BASE}/api/status`);
  if (!res.ok) throw new Error("Failed to fetch server status");
  return res.json();
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${API_BASE}/api/sessions`);
  if (!res.ok) throw new Error("Failed to fetch sessions");
  return res.json();
}

export async function fetchMessages(): Promise<ChatMessage[]> {
  const res = await fetch(`${API_BASE}/api/messages`);
  if (!res.ok) throw new Error("Failed to fetch messages");
  return res.json();
}

export async function resumeSession(sessionId: string): Promise<{ success: boolean; session_id: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error("Failed to resume session");
  return res.json();
}

export async function createNewSession(): Promise<{ success: boolean; session_id: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/new`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error("Failed to create new session");
  return res.json();
}

export async function fetchModels(): Promise<ModelChoice[]> {
  const res = await fetch(`${API_BASE}/api/models`);
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

export async function configureProvider(params: {
  model?: string;
  api_key?: string;
  provider?: "openai" | "anthropic";
  base_url?: string;
}): Promise<{ success: boolean; model: string; provider: string }> {
  const res = await fetch(`${API_BASE}/api/config/provider`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error("Failed to configure provider");
  return res.json();
}

export async function setThinkingLevel(level: string): Promise<{ thinking_level: string }> {
  const res = await fetch(`${API_BASE}/api/thinking`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  });
  if (!res.ok) throw new Error("Failed to set thinking level");
  return res.json();
}
