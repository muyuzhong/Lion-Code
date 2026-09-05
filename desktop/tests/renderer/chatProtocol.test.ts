import { afterEach, describe, expect, it, vi } from "vitest";
import {
  actionForInput,
  decodeServerEvent,
  formatRunDuration,
  initialChatProtocolState,
  openableResourceForTool,
  reduceChatProtocol,
  type ChatProtocolState,
  type ServerEvent,
} from "../../src/shared/chat";

const assistant = { role: "assistant" as const, content: [], stopReason: "stop" as const, errorMessage: null };
const apply = (state: ChatProtocolState, event: ServerEvent) => reduceChatProtocol(state, { type: "server_event", event });

afterEach(() => vi.restoreAllMocks());

describe("Lion chat protocol", () => {
  it("strictly rejects snake_case and malformed wire events", () => {
    expect(decodeServerEvent({ type: "confirm_request", requestId: "r1", message: "ok?" })).not.toBeNull();
    expect(decodeServerEvent({ type: "confirm_request", request_id: "r1", message: "ok?" })).toBeNull();
    expect(decodeServerEvent({ type: "queue_update", steering: [], follow_up: [] })).toBeNull();
    expect(decodeServerEvent({ type: "message_update", message: assistant })).toBeNull();
  });

  it("projects persisted results without weakening the optional wire contract", () => {
    expect(openableResourceForTool("run_shell", { command: "cat" }, { persisted_path: "C:/results/out.txt", original_bytes: 12 })).toEqual({ path: "C:/results/out.txt", expectedSize: 12 });
    expect(openableResourceForTool("run_shell", { command: "cat" }, undefined)).toBeUndefined();
    expect(decodeServerEvent({ type: "tool_execution_end", toolCallId: "t1", toolName: "read_file", result: { content: [], isError: false }, isError: false })).not.toBeNull();
    expect(decodeServerEvent({ type: "tool_execution_end", toolCallId: "t1", toolName: "read_file", result: { content: [], details: 1n, isError: false }, isError: false })).toBeNull();

    let state = apply(initialChatProtocolState, { type: "tool_execution_start", toolCallId: "t1", toolName: "read_file", args: { file_path: "notes.md" } });
    state = apply(state, { type: "tool_execution_end", toolCallId: "t1", toolName: "read_file", result: { content: [{ type: "text", text: "full" }], details: { persisted_path: "C:/results/out.txt", original_bytes: 4 }, isError: false }, isError: false });
    expect(state.messages[0].tools?.[0].openable).toEqual({ path: "C:/results/out.txt", expectedSize: 4 });
  });

  it("replaces queue snapshots and consumes matching user echoes steering-first", () => {
    let state = apply(initialChatProtocolState, { type: "queue_update", steering: ["same"], followUp: ["same", "later"] });
    state = apply(state, { type: "message_start", message: { role: "user", content: "same" } });
    expect(state.queue).toEqual({ steering: [], followUp: ["same", "later"] });
    expect(state.messages.at(-1)).toMatchObject({ role: "user", content: "same" });
    const echoed = apply(state, { type: "message_start", message: { role: "user", content: [{ type: "text", text: "missing" }] } });
    expect(echoed).toBe(state);
    const replaced = apply(state, { type: "queue_update", steering: [], followUp: ["new"] });
    expect(replaced.queue).toEqual({ steering: [], followUp: ["new"] });
  });

  it("consumes queued block content and resets the queue on canonical history", () => {
    let state = apply(initialChatProtocolState, { type: "queue_update", steering: [], followUp: ["block text"] });
    state = apply(state, { type: "message_start", message: { role: "user", content: [{ type: "text", text: "block text" }] } });
    expect(state.messages.at(-1)).toMatchObject({ role: "user", content: "block text" });
    expect(state.queue.followUp).toEqual([]);
    state = apply(state, { type: "queue_update", steering: ["stale"], followUp: [] });
    state = reduceChatProtocol(state, { type: "replace_history", messages: [] });
    expect(state.queue).toEqual({ steering: [], followUp: [] });
  });

  it("streams text and reasoning into one assistant message", () => {
    let state = apply(initialChatProtocolState, { type: "message_start", message: assistant });
    state = apply(state, { type: "message_update", message: assistant, assistantMessageEvent: { type: "text_delta", contentIndex: 0, delta: "hello", partial: assistant } });
    state = apply(state, { type: "message_update", message: assistant, assistantMessageEvent: { type: "thinking_delta", contentIndex: 1, delta: "think", partial: assistant } });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({ content: "hello", reasoning: "think", isStreaming: true });
  });

  it("keeps the unconfigured API error in reducer state", () => {
    const errorMessage = "API 未配置：请在设置面板中配置 Provider 与模型。";
    const message = {
      role: "assistant" as const,
      content: [{ type: "text" as const, text: errorMessage }],
      stopReason: "error" as const,
      errorMessage,
    };
    let state = apply(initialChatProtocolState, { type: "message_start", message });
    state = apply(state, { type: "message_end", message });

    expect(state.messages.at(-1)).toMatchObject({ content: errorMessage, error: errorMessage, isStreaming: false });
  });

  it("pairs parallel tools by toolCallId even when they finish out of order", () => {
    let state = apply(initialChatProtocolState, { type: "tool_execution_start", toolCallId: "a", toolName: "read", args: { path: "a" } });
    state = apply(state, { type: "tool_execution_start", toolCallId: "b", toolName: "exec", args: { cmd: "test" } });
    state = apply(state, { type: "tool_execution_end", toolCallId: "b", toolName: "exec", result: { content: [{ type: "text", text: "bad" }], isError: true }, isError: true });
    state = apply(state, { type: "tool_execution_end", toolCallId: "a", toolName: "read", result: { content: [{ type: "text", text: "ok" }], isError: false }, isError: false });
    expect(state.messages[0].tools).toEqual([
      expect.objectContaining({ id: "a", status: "completed", result: "ok" }),
      expect.objectContaining({ id: "b", status: "error", result: "bad" }),
    ]);
  });

  it("tracks runtime notices, metrics, and resets local state on canonical history", () => {
    vi.spyOn(Date, "now").mockReturnValueOnce(100).mockReturnValueOnce(175);
    let state = apply(initialChatProtocolState, { type: "turn_start" });
    state = apply(state, { type: "message_start", message: assistant });
    state = apply(state, { type: "message_end", message: assistant });
    state = apply(state, { type: "auto_retry_start", attempt: 2, maxAttempts: 3, delayMs: 500, errorMessage: "busy" });
    expect(state.metrics).toMatchObject({ steps: 1, llmMs: 75 });
    expect(state.runtimeNotice?.kind).toBe("retry");
    state = reduceChatProtocol(state, { type: "replace_history", messages: [{ id: "h1", role: "assistant", content: "history" }] });
    expect(state.metrics).toMatchObject({ steps: 0, llmMs: 0, toolMs: 0 });
    expect(state.runtimeNotice).toBeNull();
    expect(state.queue).toEqual({ steering: [], followUp: [] });
  });

  it("clears retry and compaction notices on success, failure, and terminal fallback", () => {
    let state = apply(initialChatProtocolState, { type: "auto_retry_start", attempt: 1, maxAttempts: 2, delayMs: 10, errorMessage: "busy" });
    state = apply(state, { type: "auto_retry_end", success: true, attempt: 1, finalError: null });
    expect(state.runtimeNotice).toBeNull();
    state = apply(state, { type: "compaction_started", reason: "threshold" });
    state = apply(state, { type: "compaction_completed", reason: "threshold", aborted: false });
    expect(state.runtimeNotice).toBeNull();
    state = apply(state, { type: "compaction_start", reason: "overflow" });
    state = apply(state, { type: "compaction_end", reason: "overflow", aborted: true, willRetry: false, errorMessage: "failed" });
    expect(state.runtimeNotice).toBeNull();
    expect(state.messages.at(-1)?.error).toBe("failed");
    state = apply(state, { type: "compaction_started", reason: "threshold" });
    state = apply(state, { type: "agent_settled" });
    expect(state.runtimeNotice).toBeNull();
  });

  it("tracks reasoning and ignores orphan tool timing", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    let state = apply(initialChatProtocolState, { type: "message_start", message: assistant });
    state = apply(state, { type: "message_update", message: assistant, assistantMessageEvent: { type: "thinking_start", contentIndex: 0, partial: assistant } });
    now.mockReturnValue(2_500);
    state = apply(state, { type: "message_update", message: assistant, assistantMessageEvent: { type: "thinking_end", contentIndex: 0, content: "thought", partial: assistant } });
    state = apply(state, { type: "message_end", message: { ...assistant, content: [{ type: "thinking", thinking: "thought" }] } });
    expect(state.messages[0].reasoningDuration).toBe(1_500);
    state = apply(state, { type: "tool_execution_end", toolCallId: "orphan", toolName: "read", result: { content: [], isError: false }, isError: false });
    expect(state.metrics.toolMs).toBe(0);
  });

  it("formats duration boundaries without 60-second artifacts", () => {
    expect(formatRunDuration(59_999)).toBe("1m0s");
    expect(formatRunDuration(119_700)).toBe("2m0s");
  });

  it("fails approvals closed on disconnect without clearing the server queue", () => {
    let state = apply(initialChatProtocolState, { type: "queue_update", steering: ["keep"], followUp: [] });
    state = apply(state, { type: "confirm_request", requestId: "r1", message: "approve?" });
    state = apply(state, { type: "plan_approval_request", requestId: "p1", plan: "plan" });
    state = reduceChatProtocol(state, { type: "disconnected" });
    expect(state.confirmRequest).toBeNull();
    expect(state.planApprovalRequest).toBeNull();
    expect(state.queue.steering).toEqual(["keep"]);
  });

  it("encodes prompt, continue, compact and slash commands without aliases", () => {
    expect(actionForInput("hello")).toEqual({ action: "prompt", prompt: "hello" });
    expect(actionForInput("/continue")).toEqual({ action: "continue" });
    expect(actionForInput("/compact")).toEqual({ action: "compact" });
    expect(actionForInput("/plan")).toEqual({ action: "command", command: "/plan" });
  });
});
