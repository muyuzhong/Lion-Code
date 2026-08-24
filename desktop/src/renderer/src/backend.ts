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

async function responseDetail(response: Response, fallback: string): Promise<string> {
  try {
    const value: unknown = await response.json();
    return isRecord(value) && typeof value.detail === "string" ? value.detail : fallback;
  } catch {
    return fallback;
  }
}
