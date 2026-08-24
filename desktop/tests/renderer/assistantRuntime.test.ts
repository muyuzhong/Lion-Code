import { describe, expect, it, vi } from "vitest";
import type { BackendBootstrap, WebSocketPort } from "../../src/renderer/src/backend";
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

function harness(history: unknown[] = []) {
  const sockets: FakeSocket[] = [];
  const requests: Array<{ url: string; authorization: string | null; body: string | null }> = [];
  let reconnect: (() => void) | null = null;
  const bootstrap: BackendBootstrap = {
    endpoint: { baseUrl: "http://127.0.0.1:4567", capability: "a".repeat(32) },
    fetch: async (input, init) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      requests.push({ url, authorization: headers.get("Authorization"), body: typeof init?.body === "string" ? init.body : null });
      const payload = url.endsWith("/api/messages") ? history
        : url.endsWith("/api/status") ? { session_id: "s1", model: "model-a", provider_name: "anthropic", permission_mode: "default", api_configured: true, cwd: "C:/work", thinking_level: "medium", available_thinking_levels: ["off", "medium"], input_tokens: 12, output_tokens: 4, is_running: false }
          : url.endsWith("/api/sessions") ? [{ id: "s1", label: null, startTime: null, messageCount: 2, cwd: "C:/work" }]
            : url.endsWith("/api/models") ? [{ provider_name: "anthropic", model: "model-a" }]
              : url.endsWith("/api/skills") ? [{ name: "review", description: "Review changes" }]
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
