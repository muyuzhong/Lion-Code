import { ChatMessage, ModelChoice, ServerStatus, SessionSummary } from "@/types/chat";
import { capabilityHeaders } from "@/lib/capability";

const API_BASE = "";

function authorizedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: capabilityHeaders(init.headers),
  });
}

export async function fetchStatus(): Promise<ServerStatus> {
  const res = await authorizedFetch("/api/status");
  if (!res.ok) throw new Error("Failed to fetch server status");
  return res.json();
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const res = await authorizedFetch("/api/sessions");
  if (!res.ok) throw new Error("Failed to fetch sessions");
  return res.json();
}

export async function fetchMessages(): Promise<ChatMessage[]> {
  const res = await authorizedFetch("/api/messages");
  if (!res.ok) throw new Error("Failed to fetch messages");
  return res.json();
}

export async function resumeSession(sessionId: string): Promise<{ success: boolean; session_id: string }> {
  const res = await authorizedFetch("/api/sessions/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) {
    let detail = "Failed to resume session";
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      // 非 JSON 错误响应时保留默认信息
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function createNewSession(): Promise<{ success: boolean; session_id: string }> {
  const res = await authorizedFetch("/api/sessions/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error("Failed to create new session");
  return res.json();
}

export async function fetchModels(): Promise<ModelChoice[]> {
  const res = await authorizedFetch("/api/models");
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

export async function configureProvider(params: {
  model?: string;
  api_key?: string;
  provider?: "openai" | "anthropic";
  base_url?: string;
}): Promise<{ success: boolean; model: string; provider: string }> {
  const res = await authorizedFetch("/api/config/provider", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    let detail = "Failed to configure provider";
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      // 非 JSON 错误响应时保留默认信息
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function setThinkingLevel(level: string): Promise<{ thinking_level: string }> {
  const res = await authorizedFetch("/api/thinking", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  });
  if (!res.ok) throw new Error("Failed to set thinking level");
  return res.json();
}
