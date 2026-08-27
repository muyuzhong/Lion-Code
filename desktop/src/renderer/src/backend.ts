import type { BackendEndpoint } from "../../shared/types";
import { decodeServerEvent, type ChatMessage, type ClientAction, type ServerEvent } from "../../shared/chat";

const CAPABILITY_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;
const WEBSOCKET_PROTOCOL = "lion-code";
const WEBSOCKET_CAPABILITY_PREFIX = "lion-code-capability.";

export interface WebSocketPort {
  readonly readyState: number;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  send(data: string): void;
  close(): void;
}

export interface BackendBootstrap {
  endpoint: BackendEndpoint;
  fetch: typeof globalThis.fetch;
  createWebSocket(url: string, protocols: string[]): WebSocketPort;
  scheduleReconnect(callback: () => void, delayMs: number): number;
  cancelReconnect(id: number): void;
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
  label: string | null;
  startTime: string | null;
  messageCount: number;
  cwd: string | null;
}

export interface ModelChoice { provider_name: string; model: string }
export interface SkillSummary { name: string; description: string | null }
export interface ProviderConfiguration {
  provider?: "openai" | "anthropic";
  model?: string;
  api_key?: string;
  base_url?: string;
}

export interface ProviderConfigurationResponse {
  provider: "openai" | "anthropic";
  model: string;
  api_key: string;
  base_url: string;
}

export interface EgressConfiguration {
  allow_hosts: string[];
}

export interface EgressConfigurationResponse {
  allow_hosts: string[];
}

export function browserBackendBootstrap(endpoint: BackendEndpoint): BackendBootstrap {
  return {
    endpoint,
    fetch: globalThis.fetch.bind(globalThis),
    createWebSocket: (url, protocols) => new WebSocket(url, protocols) as unknown as WebSocketPort,
    scheduleReconnect: (callback, delayMs) => window.setTimeout(callback, delayMs),
    cancelReconnect: (id) => window.clearTimeout(id),
  };
}

export class LionRestClient {
  constructor(private readonly bootstrap: BackendBootstrap) {}

  async fetchMessages(): Promise<ChatMessage[]> {
    const response = await this.authorizedFetch("/api/messages");
    if (!response.ok) throw new Error(`加载聊天历史失败 (${response.status})`);
    const value: unknown = await response.json();
    if (!Array.isArray(value) || !value.every(isChatMessage)) {
      throw new Error("聊天历史不符合 REST 契约");
    }
    return value;
  }

  async resumeSession(sessionId: string): Promise<void> {
    const response = await this.authorizedFetch("/api/sessions/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok) throw new Error(await responseDetail(response, "切换会话失败"));
  }

  async fetchStatus(): Promise<ServerStatus> {
    return this.readJson("/api/status", isServerStatus, "状态不符合 REST 契约");
  }

  async fetchSessions(): Promise<SessionSummary[]> {
    return this.readArray("/api/sessions", isSessionSummary, "会话列表不符合 REST 契约");
  }

  async fetchModels(): Promise<ModelChoice[]> {
    return this.readArray("/api/models", isModelChoice, "模型列表不符合 REST 契约");
  }

  async fetchSkills(): Promise<SkillSummary[]> {
    return this.readArray("/api/skills", isSkillSummary, "Skill 列表不符合 REST 契约");
  }

  async fetchProviderConfiguration(): Promise<ProviderConfigurationResponse> {
    return this.readJson("/api/config/provider", isProviderConfiguration, "Provider 配置不符合 REST 契约");
  }

  async fetchEgressConfiguration(): Promise<EgressConfigurationResponse> {
    return this.readJson("/api/config/egress", isEgressConfiguration, "Egress 配置不符合 REST 契约");
  }

  async newSession(): Promise<void> {
    await this.postJson("/api/sessions/new", {});
  }

  async renameSession(sessionId: string, label: string): Promise<void> {
    await this.postJson("/api/sessions/rename", { session_id: sessionId, label });
  }

  async configureProvider(configuration: ProviderConfiguration): Promise<void> {
    await this.postJson("/api/config/provider", configuration);
  }

  async configureEgress(configuration: EgressConfiguration): Promise<void> {
    await this.postJson("/api/config/egress", configuration);
  }

  async setThinkingLevel(level: string): Promise<void> {
    await this.postJson("/api/thinking", { level });
  }

  private async readJson<T>(path: string, guard: (value: unknown) => value is T, invalid: string): Promise<T> {
    const response = await this.authorizedFetch(path);
    if (!response.ok) throw new Error(await responseDetail(response, `请求失败 (${response.status})`));
    const value: unknown = await response.json();
    if (!guard(value)) throw new Error(invalid);
    return value;
  }

  private async readArray<T>(path: string, guard: (value: unknown) => value is T, invalid: string): Promise<T[]> {
    const response = await this.authorizedFetch(path);
    if (!response.ok) throw new Error(await responseDetail(response, `请求失败 (${response.status})`));
    const value: unknown = await response.json();
    if (!Array.isArray(value) || !value.every(guard)) throw new Error(invalid);
    return value;
  }

  private async postJson(path: string, body: object): Promise<void> {
    const response = await this.authorizedFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await responseDetail(response, `请求失败 (${response.status})`));
  }

  private authorizedFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.bootstrap.endpoint.capability}`);
    return this.bootstrap.fetch(new URL(path, this.bootstrap.endpoint.baseUrl), { ...init, headers });
  }
}

export type TransportEvent =
  | { type: "connected" }
  | { type: "disconnected" }
  | { type: "event"; event: ServerEvent }
  | { type: "protocol_error"; message: string }
  | { type: "transport_error"; message: string };

export class LionWebSocketTransport {
  private socket: WebSocketPort | null = null;

  constructor(
    private readonly bootstrap: BackendBootstrap,
    private readonly listener: (event: TransportEvent) => void,
  ) {}

  connect(): void {
    if (this.socket && (this.socket.readyState === 1 || this.socket.readyState === 0)) return;
    const endpoint = this.bootstrap.endpoint;
    if (!CAPABILITY_PATTERN.test(endpoint.capability)) {
      this.listener({ type: "transport_error", message: "Backend capability 非法" });
      return;
    }
    const url = new URL("/ws/chat", endpoint.baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = this.bootstrap.createWebSocket(url.toString(), [
      WEBSOCKET_PROTOCOL,
      `${WEBSOCKET_CAPABILITY_PREFIX}${endpoint.capability}`,
    ]);
    this.socket = socket;
    socket.onopen = () => this.listener({ type: "connected" });
    socket.onerror = () => this.listener({ type: "transport_error", message: "WebSocket 连接错误" });
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null;
      this.listener({ type: "disconnected" });
    };
    socket.onmessage = ({ data }) => {
      try {
        if (typeof data !== "string") throw new Error("非文本帧");
        const event = decodeServerEvent(JSON.parse(data));
        if (!event) throw new Error("事件 schema 非法");
        this.listener({ type: "event", event });
      } catch {
        this.listener({ type: "protocol_error", message: "服务端消息不符合 WebSocket event 契约" });
      }
    };
  }

  send(action: ClientAction): boolean {
    if (!this.socket || this.socket.readyState !== 1) return false;
    this.socket.send(JSON.stringify(action));
    return true;
  }

  close(): boolean {
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    return socket !== null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (!isRecord(value) || typeof value.id !== "string" || (value.role !== "user" && value.role !== "assistant") || typeof value.content !== "string") return false;
  if (value.reasoning !== undefined && value.reasoning !== null && typeof value.reasoning !== "string") return false;
  if (value.error !== undefined && value.error !== null && typeof value.error !== "string") return false;
  if (value.createdAt !== undefined && value.createdAt !== null && typeof value.createdAt !== "string") return false;
  if (value.tools !== undefined && (!Array.isArray(value.tools) || !value.tools.every(isToolCall))) return false;
  return true;
}

function isToolCall(value: unknown): boolean {
  return isRecord(value) && typeof value.id === "string" && typeof value.toolName === "string" && (value.status === "running" || value.status === "completed" || value.status === "error") && (value.args === undefined || typeof value.args === "string" || isRecord(value.args)) && (value.result === undefined || value.result === null || typeof value.result === "string");
}

function isServerStatus(value: unknown): value is ServerStatus {
  return isRecord(value)
    && typeof value.session_id === "string"
    && typeof value.model === "string"
    && typeof value.provider_name === "string"
    && typeof value.permission_mode === "string"
    && typeof value.api_configured === "boolean"
    && typeof value.cwd === "string"
    && typeof value.thinking_level === "string"
    && Array.isArray(value.available_thinking_levels)
    && value.available_thinking_levels.every((level) => typeof level === "string")
    && typeof value.input_tokens === "number"
    && typeof value.output_tokens === "number"
    && typeof value.is_running === "boolean";
}

function isSessionSummary(value: unknown): value is SessionSummary {
  return isRecord(value)
    && typeof value.id === "string"
    && (value.label === null || typeof value.label === "string")
    && (value.startTime === null || typeof value.startTime === "string")
    && typeof value.messageCount === "number"
    && (value.cwd === null || typeof value.cwd === "string");
}

function isModelChoice(value: unknown): value is ModelChoice {
  return isRecord(value) && typeof value.provider_name === "string" && typeof value.model === "string";
}

function isSkillSummary(value: unknown): value is SkillSummary {
  return isRecord(value) && typeof value.name === "string" && (value.description === null || typeof value.description === "string");
}

function isProviderConfiguration(value: unknown): value is ProviderConfigurationResponse {
  return isRecord(value)
    && (value.provider === "openai" || value.provider === "anthropic")
    && typeof value.model === "string"
    && typeof value.api_key === "string"
    && typeof value.base_url === "string";
}

function isEgressConfiguration(value: unknown): value is EgressConfigurationResponse {
  return isRecord(value)
    && Array.isArray(value.allow_hosts)
    && value.allow_hosts.every((item) => typeof item === "string");
}

async function responseDetail(response: Response, fallback: string): Promise<string> {
  try {
    const value: unknown = await response.json();
    return isRecord(value) && typeof value.detail === "string" ? value.detail : fallback;
  } catch {
    return fallback;
  }
}
