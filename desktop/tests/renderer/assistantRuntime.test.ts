import { describe, expect, it, vi } from "vitest";
import { isOpenableResourceResponse, LionRestClient, type BackendBootstrap, type WebSocketPort } from "../../src/renderer/src/backend";
import { projectLionMessage } from "../../src/renderer/src/assistantRuntime";
import { LionAssistantRuntimeAdapter } from "../../src/renderer/src/lionRuntime";

class FakeSocket implements WebSocketPort {
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  sent: string[] = [];
  open() { this.readyState = 1; this.onopen?.(); }
  receive(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; this.onclose?.(); }
}

function harness(history: unknown[] = [], options: { apiConfigured?: boolean; blockMetadataPath?: string; providerConfiguration?: unknown; status?: unknown; resourceResponse?: unknown } = {}) {
  const sockets: FakeSocket[] = [];
  const requests: Array<{ url: string; authorization: string | null; body: string | null }> = [];
  let reconnect: (() => void) | null = null;
  const bootstrap: BackendBootstrap = {
    endpoint: { baseUrl: "http://127.0.0.1:4567", capability: "a".repeat(32) },
    fetch: async (input, init) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      requests.push({ url, authorization: headers.get("Authorization"), body: typeof init?.body === "string" ? init.body : null });
      if (options.blockMetadataPath && url.endsWith(options.blockMetadataPath)) {
        return new Promise<Response>(() => {});
      }
      const status = options.status === undefined ? { session_id: "s1", model: "model-a", provider_name: "anthropic", permission_mode: "default", api_configured: options.apiConfigured ?? true, provider_blocker_code: options.apiConfigured === false ? "provider_configuration_required" : null, cwd: "C:/work", thinking_level: "medium", available_thinking_levels: ["off", "medium"], input_tokens: 12, output_tokens: 4, is_running: false } : options.status;
      const payload = url.includes("/api/resources/open") ? options.resourceResponse ?? { status: "ready", path: "C:/work/file.txt", name: "file.txt", format: "text", size: 4, modifiedAtNs: "1", content: "data", message: null }
        : url.endsWith("/api/messages") ? history
        : url.endsWith("/api/status") ? status
          : url.endsWith("/api/sessions") ? [{ id: "s1", label: null, startTime: null, messageCount: 2, cwd: "C:/work" }]
              : url.endsWith("/api/models") ? [{ provider_name: "anthropic", model: "model-a" }]
                : url.endsWith("/api/skills") ? [{ name: "review", description: "Review changes" }]
                  : url.endsWith("/api/config/provider") ? options.providerConfiguration ?? { provider: "anthropic", model: "model-a", api_key: "test-secret", base_url: "https://api.anthropic.com/v1" }
                : { success: true };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    },
    createWebSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket; },
    scheduleReconnect: (callback) => { reconnect = callback; return 7; },
    cancelReconnect: () => { reconnect = null; },
  };
  return { bootstrap, sockets, requests, runReconnect: () => reconnect?.() };
}

describe("Lion assistant runtime adapter", () => {
  it("projects text, reasoning and tools to assistant-ui parts", () => {
    const projected = projectLionMessage({ id: "a1", role: "assistant", content: "answer", reasoning: "thought", tools: [{ id: "t1", toolName: "read", args: { path: "a" }, status: "error", result: "bad" }], error: "failed" });
    expect(projected.id).toBe("a1");
    expect(projected.content).toEqual([
      { type: "reasoning", text: "thought" },
      { type: "text", text: "answer" },
      expect.objectContaining({ type: "tool-call", toolCallId: "t1", toolName: "read", isError: true, result: "bad" }),
    ]);
    expect(projected.status).toMatchObject({ type: "incomplete", reason: "error" });
  });

  it("projects an openable tool artifact for assistant-ui", () => {
    const projected = projectLionMessage({
      id: "a1",
      role: "assistant",
      content: "answer",
      tools: [{ id: "t1", toolName: "read_file", args: { file_path: "notes.md" }, status: "completed", result: "content", openable: { path: "notes.md" } }],
    });
    expect(projected.content).toEqual([
      expect.objectContaining({ type: "text", text: "answer" }),
      expect.objectContaining({ type: "tool-call", artifact: { path: "notes.md" } }),
    ]);
  });

  it("reads an openable resource through the protected REST client", async () => {
    const resource = { status: "ready", path: "C:/work/notes.md", name: "notes.md", format: "markdown", size: 9, modifiedAtNs: "1710000000000000000", content: "# Notes\n", message: null };
    const h = harness([], { resourceResponse: resource });
    const client = new LionRestClient(h.bootstrap);

    await expect(client.openResource({ path: "notes.md", expectedSize: 9 }, "1710000000000000000")).resolves.toEqual(resource);
    const request = h.requests.find((item) => item.url.includes("/api/resources/open"));
    expect(request?.url).toContain("path=notes.md");
    expect(request?.url).toContain("expected_size=9");
    expect(request?.url).toContain("expected_mtime_ns=1710000000000000000");
    expect(request?.authorization).toBe(`Bearer ${"a".repeat(32)}`);
  });

  it("fails closed for malformed resource response semantics", () => {
    const base = { path: "C:/work/file.txt", name: "file.txt", format: "text", size: 4, modifiedAtNs: "1", message: null };
    expect(isOpenableResourceResponse({ ...base, status: "ready", content: "data" })).toBe(true);
    expect(isOpenableResourceResponse({ ...base, status: "ready", content: null })).toBe(false);
    expect(isOpenableResourceResponse({ ...base, status: "binary", content: "secret" })).toBe(false);
    expect(isOpenableResourceResponse({ ...base, status: "ready", content: "data", modifiedAtNs: "not-a-timestamp" })).toBe(false);
    expect(isOpenableResourceResponse({ ...base, status: "ready", content: "data", extra: true })).toBe(false);
  });

  it("drops a stale resource response after a newer open request", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    const originalFetch = h.bootstrap.fetch;
    let resourceCalls = 0;
    let resolveFirst!: (response: Response) => void;
    const firstResponse = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    const secondResource = { status: "ready", path: "C:/work/new.txt", name: "new.txt", format: "text", size: 3, modifiedAtNs: "2", content: "new", message: null };
    h.bootstrap.fetch = async (input, init) => {
      if (String(input).includes("/api/resources/open")) {
        resourceCalls += 1;
        return resourceCalls === 1 ? firstResponse : new Response(JSON.stringify(secondResource), { status: 200 });
      }
      return originalFetch(input, init);
    };

    const oldOpen = adapter.openResource({ path: "old.txt" });
    await vi.waitFor(() => expect(adapter.getSnapshot().openedResource?.loading).toBe(true));
    const newOpen = adapter.openResource({ path: "new.txt" });
    await newOpen;
    resolveFirst(new Response(JSON.stringify({ status: "ready", path: "C:/work/old.txt", name: "old.txt", format: "text", size: 3, modifiedAtNs: "1", content: "old", message: null }), { status: 200 }));
    await oldOpen;

    expect(adapter.getSnapshot().openedResource?.response?.content).toBe("new");
    expect(adapter.getSnapshot().openedResource?.ref.path).toBe("new.txt");
  });

  it("clears the opened resource when switching the Python-owned session", async () => {
    const h = harness([], { resourceResponse: { status: "ready", path: "C:/work/file.txt", name: "file.txt", format: "text", size: 4, modifiedAtNs: "1", content: "data", message: null } });
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    await adapter.openResource({ path: "file.txt" });
    expect(adapter.getSnapshot().openedResource?.response?.status).toBe("ready");

    await adapter.switchSession("session-2");
    await vi.waitFor(() => expect(adapter.getSnapshot().openedResource).toBeNull());
  });

  it("clears the opened resource when reconnect replaces canonical history", async () => {
    const h = harness([], { resourceResponse: { status: "ready", path: "C:/work/file.txt", name: "file.txt", format: "text", size: 4, modifiedAtNs: "1", content: "data", message: null } });
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    await adapter.openResource({ path: "file.txt" });
    expect(adapter.getSnapshot().openedResource).not.toBeNull();

    h.sockets[0].close();
    await h.runReconnect?.();

    await vi.waitFor(() => expect(adapter.getSnapshot().openedResource).toBeNull());
  });

  it("loads REST history before opening WS and maps every client action", async () => {
    const h = harness([{ id: "u1", role: "user", content: "history", tools: [] }]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    expect(adapter.getSnapshot().protocol.messages[0].content).toBe("history");
    expect(h.requests[0]).toMatchObject({ url: "http://127.0.0.1:4567/api/messages", authorization: `Bearer ${"a".repeat(32)}` });
    const socket = h.sockets[0];
    socket.open();
    adapter.sendInput("hello");
    adapter.sendInput("");
    adapter.sendSteer("now");
    adapter.sendFollowUp("later");
    adapter.compact();
    adapter.respondConfirm("c1", false);
    adapter.respondPlanApproval("p1", "keep-planning", "more");
    adapter.cancel();
    expect(socket.sent.map((value) => JSON.parse(value))).toEqual([
      { action: "prompt", prompt: "hello" },
      { action: "continue" },
      { action: "steer", prompt: "now" },
      { action: "follow_up", prompt: "later" },
      { action: "compact" },
      { action: "confirm_response", requestId: "c1", approved: false },
      { action: "plan_approval_response", requestId: "p1", choice: "keep-planning", feedback: "more" },
      { action: "cancel" },
    ]);
  });

  it("projects desktop metadata and refreshes it after Provider and Thinking writes", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    await vi.waitFor(() => expect(adapter.getSnapshot().status?.session_id).toBe("s1"));
    expect(adapter.getSnapshot().sessions[0].messageCount).toBe(2);
    expect(adapter.getSnapshot().skills[0].name).toBe("review");
    expect(await adapter.configureProvider({ provider: "anthropic", model: "model-a", api_key: "secret" })).toBe(true);
    expect(await adapter.setThinkingLevel("medium")).toBe(true);
    expect(h.requests.find((request) => request.url.endsWith("/api/config/provider"))?.body).toBe(JSON.stringify({ provider: "anthropic", model: "model-a", api_key: "secret" }));
    expect(h.requests.find((request) => request.url.endsWith("/api/thinking"))?.body).toBe(JSON.stringify({ level: "medium" }));
  });

  it("accepts only the two consistent Provider status combinations", async () => {
    const validStatus = {
      session_id: "s1",
      model: "model-a",
      provider_name: "anthropic",
      permission_mode: "default",
      api_configured: true,
      provider_blocker_code: null,
      cwd: "C:/work",
      thinking_level: "medium",
      available_thinking_levels: ["off", "medium"],
      input_tokens: 12,
      output_tokens: 4,
      is_running: false,
    };

    await expect(new LionRestClient(harness([], { status: validStatus }).bootstrap).fetchStatus()).resolves.toMatchObject({
      api_configured: true,
      provider_blocker_code: null,
    });
    await expect(new LionRestClient(harness([], { status: { ...validStatus, api_configured: false, provider_blocker_code: "provider_configuration_required" } }).bootstrap).fetchStatus()).resolves.toMatchObject({
      api_configured: false,
      provider_blocker_code: "provider_configuration_required",
    });
  });

  it("rejects missing, unknown, or inconsistent Provider status codes", async () => {
    const validStatus = {
      session_id: "s1",
      model: "model-a",
      provider_name: "anthropic",
      permission_mode: "default",
      api_configured: true,
      provider_blocker_code: null,
      cwd: "C:/work",
      thinking_level: "medium",
      available_thinking_levels: ["off", "medium"],
      input_tokens: 12,
      output_tokens: 4,
      is_running: false,
    };
    const missingCode = { ...validStatus, provider_blocker_code: undefined };
    const malformedStatuses: unknown[] = [
      missingCode,
      { ...validStatus, provider_blocker_code: "unknown" },
      { ...validStatus, provider_blocker_code: "provider_configuration_required" },
      { ...validStatus, api_configured: false },
    ];

    for (const status of malformedStatuses) {
      await expect(new LionRestClient(harness([], { status }).bootstrap).fetchStatus()).rejects.toThrow("状态不符合 REST 契约");
    }
  });

  it("reads the canonical Provider configuration through the protected REST client", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();

    await expect(adapter.fetchProviderConfiguration()).resolves.toEqual({
      provider: "anthropic",
      model: "model-a",
      api_key: "test-secret",
      base_url: "https://api.anthropic.com/v1",
    });
    expect(h.requests.some((request) => request.url.endsWith("/api/config/provider") && request.authorization === `Bearer ${"a".repeat(32)}`)).toBe(true);
  });

  it("rejects a malformed Provider configuration and reports metadata error", async () => {
    const h = harness([], { providerConfiguration: { provider: "anthropic", model: "model-a", api_key: "test-secret", base_url: null } });
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();

    await expect(adapter.fetchProviderConfiguration()).resolves.toBeNull();
    expect(adapter.getSnapshot().metadataError).toBe("Provider 配置不符合 REST 契约");
  });

  it("does not block a successful Provider write on a hanging metadata request", async () => {
    const h = harness([], { blockMetadataPath: "/api/skills" });
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();

    await expect(adapter.configureProvider({ provider: "anthropic", model: "model-a" })).resolves.toBe(true);
    expect(h.requests.some((request) => request.url.endsWith("/api/config/provider"))).toBe(true);
  });

  it("projects an unconfigured API error received from the sidecar", async () => {
    const h = harness([], { apiConfigured: false });
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    h.sockets[0].open();
    const errorMessage = "API 未配置：请在设置面板中配置 Provider 与模型。";
    const message = { role: "assistant" as const, content: [{ type: "text" as const, text: errorMessage }], stopReason: "error" as const, errorMessage };

    h.sockets[0].receive({ type: "message_start", message });
    h.sockets[0].receive({ type: "message_end", message });

    const visible = adapter.getSnapshot().protocol.messages.at(-1);
    expect(visible).toMatchObject({ content: errorMessage, error: errorMessage, isStreaming: false });
    expect(projectLionMessage(visible!).status).toMatchObject({ type: "incomplete", reason: "error", error: errorMessage });
  });

  it("renames a Python-owned session and refreshes canonical metadata", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    await vi.waitFor(() => expect(adapter.getSnapshot().sessions).toHaveLength(1));
    expect(await adapter.renameSession("s1", "需求文档")).toBe(true);
    expect(h.requests.find((request) => request.url.endsWith("/api/sessions/rename"))?.body).toBe(JSON.stringify({ session_id: "s1", label: "需求文档" }));
    expect(h.requests.filter((request) => request.url.endsWith("/api/sessions"))).toHaveLength(2);
  });

  it("folds WS events and refreshes canonical history before reconnect", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    h.sockets[0].open();
    h.sockets[0].receive({ type: "message_start", message: { role: "assistant", content: [], stopReason: "stop", errorMessage: null } });
    h.sockets[0].receive({ type: "message_update", message: { role: "assistant", content: [], stopReason: "stop", errorMessage: null }, assistantMessageEvent: { type: "text_delta", contentIndex: 0, delta: "live", partial: { role: "assistant", content: [], stopReason: "stop", errorMessage: null } } });
    expect(adapter.getSnapshot().protocol.messages).toHaveLength(1);
    expect(adapter.getSnapshot().protocol.messages[0].content).toBe("live");
    h.sockets[0].close();
    expect(adapter.getSnapshot().transportStatus).toBe("reconnecting");
    h.runReconnect();
    await vi.waitFor(() => expect(h.sockets).toHaveLength(2));
    expect(h.requests.filter((request) => request.url.endsWith("/api/messages"))).toHaveLength(2);
  });

  it("turns invalid WS payloads into a visible terminal protocol error", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    h.sockets[0].open();
    h.sockets[0].receive({ type: "confirm_request", request_id: "bad", message: "bad" });
    expect(adapter.getSnapshot().transportStatus).toBe("error");
    expect(adapter.getSnapshot().transportError).toContain("不符合");
    expect(adapter.getSnapshot().protocol.messages.at(-1)?.error).toContain("不符合");
    expect(h.sockets[0].readyState).toBe(3);
  });

  it("invalidates a pending reconnect when switching sessions", async () => {
    const h = harness([]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    h.sockets[0].open();
    h.sockets[0].close();
    await adapter.switchSession("session-2");
    h.runReconnect();
    await Promise.resolve();
    expect(h.sockets).toHaveLength(2);
    expect(adapter.getSnapshot().transportStatus).toBe("loading");
  });

  it("switches the Python-owned session before replacing history and reopening WS", async () => {
    const h = harness([{ id: "u1", role: "user", content: "canonical", tools: [] }]);
    const adapter = new LionAssistantRuntimeAdapter(h.bootstrap);
    await adapter.start();
    h.sockets[0].open();
    await adapter.switchSession("session-2");
    expect(h.requests.find((request) => request.url.endsWith("/api/sessions/resume"))?.body).toBe(JSON.stringify({ session_id: "session-2" }));
    expect(h.requests.filter((request) => request.url.endsWith("/api/messages"))).toHaveLength(2);
    expect(h.sockets).toHaveLength(2);
    expect(adapter.getSnapshot().protocol.messages[0].content).toBe("canonical");
  });
});
