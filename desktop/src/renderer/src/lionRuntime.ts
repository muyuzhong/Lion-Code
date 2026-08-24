import {
  actionForInput,
  initialChatProtocolState,
  reduceChatProtocol,
  type ChatMessage,
  type ChatProtocolState,
  type ClientAction,
  type PlanApprovalChoice,
} from "../../shared/chat";
import {
  LionRestClient,
  LionWebSocketTransport,
  type BackendBootstrap,
  type ModelChoice,
  type ProviderConfiguration,
  type ServerStatus,
  type SessionSummary,
  type SkillSummary,
  type TransportEvent,
} from "./backend";

export type LionTransportStatus = "idle" | "loading" | "connected" | "reconnecting" | "error" | "closed";

export interface LionRuntimeSnapshot {
  protocol: ChatProtocolState;
  transportStatus: LionTransportStatus;
  transportError: string | null;
  status: ServerStatus | null;
  sessions: SessionSummary[];
  models: ModelChoice[];
  skills: SkillSummary[];
  metadataError: string | null;
}

type Listener = () => void;

/**
 * Lion 协议投影的唯一 owner。Python 仍拥有 Session canonical history；这里仅折叠
 * REST 快照与当前 WS run，不持久化 Provider、Session 或消息状态。
 */
export class LionAssistantRuntimeAdapter {
  private snapshot: LionRuntimeSnapshot = {
    protocol: initialChatProtocolState,
    transportStatus: "idle",
    transportError: null,
    status: null,
    sessions: [],
    models: [],
    skills: [],
    metadataError: null,
  };
  private readonly listeners = new Set<Listener>();
  private readonly rest: LionRestClient;
  private readonly transport: LionWebSocketTransport;
  private reconnectId: number | null = null;
  private active = false;
  private historyRequest = 0;
  private connectionGeneration = 0;
  private controlledDisconnect = false;

  constructor(private readonly bootstrap: BackendBootstrap) {
    this.rest = new LionRestClient(bootstrap);
    this.transport = new LionWebSocketTransport(bootstrap, (event) => this.handleTransport(event));
  }

  getSnapshot = (): LionRuntimeSnapshot => this.snapshot;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  async start(): Promise<void> {
    if (this.active) return;
    this.active = true;
    const generation = ++this.connectionGeneration;
    this.setTransport("loading", null);
    const loaded = await this.loadCanonicalHistory();
    void this.refreshMetadata();
    if (this.active && loaded && generation === this.connectionGeneration) this.transport.connect();
  }

  stop(): void {
    this.active = false;
    this.connectionGeneration += 1;
    this.historyRequest += 1;
    if (this.reconnectId !== null) this.bootstrap.cancelReconnect(this.reconnectId);
    this.reconnectId = null;
    this.controlledDisconnect = true;
    if (!this.transport.close()) this.controlledDisconnect = false;
    this.dispatch({ type: "disconnected" });
    this.setTransport("closed", null);
  }

  async switchSession(sessionId: string): Promise<void> {
    const generation = ++this.connectionGeneration;
    this.historyRequest += 1;
    if (this.reconnectId !== null) this.bootstrap.cancelReconnect(this.reconnectId);
    this.reconnectId = null;
    this.controlledDisconnect = true;
    if (!this.transport.close()) this.controlledDisconnect = false;
    this.dispatch({ type: "replace_history", messages: [] });
    this.setTransport("loading", null);
    try {
      await this.rest.resumeSession(sessionId);
      const loaded = await this.loadCanonicalHistory();
      await this.refreshMetadata();
      if (this.active && loaded && generation === this.connectionGeneration) this.transport.connect();
    } catch (error) {
      this.setTransport("error", errorMessage(error));
    }
  }

  async createSession(): Promise<void> {
    if (this.snapshot.protocol.isStreaming) return;
    const generation = ++this.connectionGeneration;
    this.controlledDisconnect = true;
    if (!this.transport.close()) this.controlledDisconnect = false;
    this.setTransport("loading", null);
    try {
      await this.rest.newSession();
      this.dispatch({ type: "replace_history", messages: [] });
      await this.refreshMetadata();
      if (this.active && generation === this.connectionGeneration) this.transport.connect();
    } catch (error) {
      this.setTransport("error", errorMessage(error));
    }
  }

  async configureProvider(configuration: ProviderConfiguration): Promise<boolean> {
    try {
      await this.rest.configureProvider(configuration);
      await this.refreshMetadata();
      return true;
    } catch (error) {
      this.setMetadataError(errorMessage(error));
      return false;
    }
  }

  async setThinkingLevel(level: string): Promise<boolean> {
    try {
      await this.rest.setThinkingLevel(level);
      await this.refreshMetadata();
      return true;
    } catch (error) {
      this.setMetadataError(errorMessage(error));
      return false;
    }
  }

  sendInput(input: string): boolean {
    const action = actionForInput(input);
    if (!action) return this.send({ action: "continue" }, true);
    const sent = this.send(action, action.action === "continue");
    if (sent && action.action === "prompt") {
      this.dispatch({
        type: "append_user",
        message: { id: `user-${Date.now()}`, role: "user", content: action.prompt, createdAt: new Date().toISOString() },
      });
    }
    return sent;
  }

  sendSteer(prompt: string): boolean {
    const text = prompt.trim();
    return text.length > 0 && this.send({ action: "steer", prompt: text });
  }

  sendFollowUp(prompt: string): boolean {
    const text = prompt.trim();
    return text.length > 0 && this.send({ action: "follow_up", prompt: text });
  }

  cancel(): boolean {
    const sent = this.send({ action: "cancel" });
    if (sent) this.dispatch({ type: "disconnected" });
    return sent;
  }

  compact(): boolean { return this.send({ action: "compact" }); }

  respondConfirm(requestId: string, approved: boolean): boolean {
    const sent = this.send({ action: "confirm_response", requestId, approved });
    if (sent) this.dispatch({ type: "clear_confirm" });
    return sent;
  }

  respondPlanApproval(requestId: string, choice: PlanApprovalChoice, feedback?: string): boolean {
    const sent = this.send({ action: "plan_approval_response", requestId, choice, feedback });
    if (sent) this.dispatch({ type: "clear_plan_approval" });
    return sent;
  }

  private send(action: ClientAction, markRunning = false): boolean {
    const sent = this.transport.send(action);
    if (sent && markRunning) this.dispatch({ type: "run_requested" });
    return sent;
  }

  private async loadCanonicalHistory(): Promise<boolean> {
    const request = ++this.historyRequest;
    try {
      const messages = await this.rest.fetchMessages();
      if (!this.active || request !== this.historyRequest) return false;
      this.dispatch({ type: "replace_history", messages });
      return true;
    } catch (error) {
      if (request === this.historyRequest) this.setTransport("error", errorMessage(error));
      return false;
    }
  }

  private async refreshMetadata(): Promise<void> {
    try {
      const [status, sessions, models, skills] = await Promise.all([
        this.rest.fetchStatus(),
        this.rest.fetchSessions(),
        this.rest.fetchModels(),
        this.rest.fetchSkills(),
      ]);
      this.snapshot = { ...this.snapshot, status, sessions, models, skills, metadataError: null };
      this.emit();
    } catch (error) {
      this.setMetadataError(errorMessage(error));
    }
  }

  private handleTransport(event: TransportEvent): void {
    if (!this.active) return;
    switch (event.type) {
      case "connected":
        this.setTransport("connected", null);
        return;
      case "event":
        this.dispatch({ type: "server_event", event: event.event });
        return;
      case "protocol_error":
        this.dispatch({ type: "server_event", event: { type: "protocol_error", message: event.message } });
        this.connectionGeneration += 1;
        this.controlledDisconnect = true;
        if (!this.transport.close()) this.controlledDisconnect = false;
        this.dispatch({ type: "disconnected" });
        this.setTransport("error", event.message);
        return;
      case "transport_error":
        this.setTransport("error", event.message);
        return;
      case "disconnected":
        if (this.controlledDisconnect) {
          this.controlledDisconnect = false;
          return;
        }
        this.dispatch({ type: "disconnected" });
        this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (!this.active || this.reconnectId !== null) return;
    const generation = this.connectionGeneration;
    this.setTransport("reconnecting", null);
    this.reconnectId = this.bootstrap.scheduleReconnect(() => {
      this.reconnectId = null;
      void this.reconnect(generation);
    }, 2_000);
  }

  private async reconnect(generation: number): Promise<void> {
    if (generation !== this.connectionGeneration) return;
    const loaded = await this.loadCanonicalHistory();
    if (!this.active || generation !== this.connectionGeneration) return;
    if (loaded) this.transport.connect();
    else this.scheduleReconnect();
  }

  private dispatch(action: Parameters<typeof reduceChatProtocol>[1]): void {
    this.snapshot = { ...this.snapshot, protocol: reduceChatProtocol(this.snapshot.protocol, action) };
    this.emit();
  }

  private setTransport(transportStatus: LionTransportStatus, transportError: string | null): void {
    this.snapshot = { ...this.snapshot, transportStatus, transportError };
    this.emit();
  }

  private setMetadataError(metadataError: string | null): void {
    this.snapshot = { ...this.snapshot, metadataError };
    this.emit();
  }

  private emit(): void { this.listeners.forEach((listener) => listener()); }
}

export function messageText(message: ChatMessage): string { return message.content; }

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Backend transport error";
}
