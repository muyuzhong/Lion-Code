import { describe, expect, it, vi, afterEach } from "vitest";

import {
  actionForInput,
  decodeServerEvent,
  emptyChatMetrics,
  formatRunDuration,
  initialChatProtocolState,
  reduceChatProtocol,
  type ChatProtocolState,
  type ServerEvent,
} from "./chatProtocol";

function apply(state: ChatProtocolState, event: ServerEvent) {
  return reduceChatProtocol(state, { type: "server_event", event });
}

const emptyAssistant = {
  role: "assistant" as const,
  content: [] as never[],
  stopReason: "stop" as const,
  errorMessage: null,
};

afterEach(() => {
  vi.restoreAllMocks();
});

function startAssistant(state = initialChatProtocolState) {
  return apply(state, {
    type: "message_start",
    message: {
      role: "assistant",
      content: [],
      stopReason: "stop",
      errorMessage: null,
    },
  });
}

describe("canonical WebSocket reducer", () => {
  it("matches parallel tool results by toolCallId and extracts text content", () => {
    let state = startAssistant();
    state = apply(state, {
      type: "tool_execution_start",
      toolCallId: "call-a",
      toolName: "read_file",
      args: { path: "a.py" },
    });
    state = apply(state, {
      type: "tool_execution_start",
      toolCallId: "call-b",
      toolName: "exec_command",
      args: { command: "pytest" },
    });
    state = apply(state, {
      type: "tool_execution_end",
      toolCallId: "call-b",
      toolName: "exec_command",
      result: {
        content: [
          { type: "text", text: "failed" },
          { type: "image", data: "ignored", mimeType: "image/png" },
        ],
        isError: true,
      },
      isError: true,
    });
    state = apply(state, {
      type: "tool_execution_end",
      toolCallId: "call-a",
      toolName: "read_file",
      result: {
        content: [{ type: "text", text: "source" }],
        isError: false,
      },
      isError: false,
    });

    expect(state.messages[0].tools).toEqual([
      expect.objectContaining({
        id: "call-a",
        status: "completed",
        result: "source",
      }),
      expect.objectContaining({
        id: "call-b",
        status: "error",
        result: "failed",
      }),
    ]);
  });

  it("reconciles a final assistant message with canonical block content", () => {
    let state = startAssistant();
    state = apply(state, {
      type: "message_update",
      message: {
        role: "assistant",
        content: [],
        stopReason: "stop",
        errorMessage: null,
      },
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "provisional",
        partial: {
          role: "assistant",
          content: [],
          stopReason: "stop",
          errorMessage: null,
        },
      },
    });
    state = apply(state, {
      type: "message_end",
      message: {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "canonical thought" },
          { type: "text", text: "canonical answer" },
          {
            type: "toolCall",
            id: "tool-1",
            name: "read_file",
            arguments: { path: "a.py" },
          },
        ],
        stopReason: "toolUse",
        errorMessage: null,
      },
    });

    expect(state.messages[0]).toEqual(
      expect.objectContaining({
        content: "canonical answer",
        reasoning: "canonical thought",
        isStreaming: false,
      }),
    );
    expect(state.messages[0].tools?.[0].id).toBe("tool-1");
  });

  it("makes provider, server, and protocol failures visible and terminal", () => {
    const providerFailed = apply(startAssistant(), {
      type: "message_end",
      message: {
        role: "assistant",
        content: [],
        stopReason: "error",
        errorMessage: "provider unavailable",
      },
    });
    const serverFailed = apply(startAssistant(), {
      type: "server_error",
      message: "server crashed",
    });
    const protocolFailed = apply(startAssistant(), {
      type: "protocol_error",
      message: "invalid action",
    });

    expect(providerFailed.messages[0].error).toBe("provider unavailable");
    expect(serverFailed.messages[0].error).toBe("server crashed");
    expect(protocolFailed.messages[0].error).toBe("invalid action");
    expect([providerFailed, serverFailed, protocolFailed].every((item) => !item.isStreaming)).toBe(true);
  });

  it("replaces all provisional state with canonical reconnect history", () => {
    const provisional = startAssistant();
    const history = [
      {
        id: "msg-1",
        role: "assistant" as const,
        content: "canonical",
        createdAt: null,
      },
    ];

    const restored = reduceChatProtocol(provisional, {
      type: "replace_history",
      messages: history,
    });

    expect(restored.messages).toEqual(history);
    expect(restored.currentAssistantId).toBeNull();
    expect(restored.isStreaming).toBe(false);
  });

  it("clears stale approvals immediately when the socket disconnects", () => {
    const waiting = apply(initialChatProtocolState, {
      type: "confirm_request",
      requestId: "request-1",
      message: "Approve?",
    });

    const disconnected = reduceChatProtocol(waiting, { type: "disconnected" });

    expect(disconnected.confirmRequest).toBeNull();
    expect(disconnected.planApprovalRequest).toBeNull();
  });

  it("rejects malformed and snake_case server payloads at the decoder", () => {
    expect(
      decodeServerEvent({
        type: "confirm_request",
        requestId: "request-1",
        message: "Approve?",
      }),
    ).not.toBeNull();
    expect(
      decodeServerEvent({
        type: "confirm_request",
        request_id: "request-1",
        message: "Approve?",
      }),
    ).toBeNull();
    expect(
      decodeServerEvent({
        type: "tool_execution_end",
        toolCallId: "tool-1",
        toolName: "read_file",
        result: { content: [], isError: false },
        is_error: false,
      }),
    ).toBeNull();
    expect(
      decodeServerEvent({
        type: "message_update",
        message: {
          role: "assistant",
          content: [],
          stopReason: "stop",
          errorMessage: null,
        },
      }),
    ).toBeNull();
  });
});

describe("typed input actions", () => {
  it("routes slash commands and special continue/compact actions", () => {
    expect(actionForInput("/plan")).toEqual({
      action: "command",
      command: "/plan",
    });
    expect(actionForInput("/continue")).toEqual({ action: "continue" });
    expect(actionForInput("/compact")).toEqual({ action: "compact" });
    expect(actionForInput("hello")).toEqual({
      action: "prompt",
      prompt: "hello",
    });
  });
});

describe("queued interaction (steer / follow_up)", () => {
  it("replaces the queue wholesale on each queue_update snapshot", () => {
    let state = apply(initialChatProtocolState, {
      type: "queue_update",
      steering: ["改向"],
      followUp: ["第一句"],
    });
    expect(state.queue).toEqual({ steering: ["改向"], followUp: ["第一句"] });

    // 后端只发全量快照：旧条目消失说明是替换而非 append 合并
    state = apply(state, {
      type: "queue_update",
      steering: [],
      followUp: ["第二句"],
    });
    expect(state.queue).toEqual({ steering: [], followUp: ["第二句"] });
  });

  it("turns a consumed queued message into a formal user message and dequeues it", () => {
    let state = apply(initialChatProtocolState, {
      type: "queue_update",
      steering: ["先改向"],
      followUp: ["第一句", "第二句"],
    });

    state = apply(state, {
      type: "message_start",
      message: { role: "user", content: "先改向" },
    });
    expect(state.queue).toEqual({ steering: [], followUp: ["第一句", "第二句"] });
    expect(state.messages.at(-1)).toEqual(
      expect.objectContaining({ role: "user", content: "先改向" }),
    );

    state = apply(state, {
      type: "message_start",
      message: {
        role: "user",
        content: [{ type: "text", text: "第一句" }],
      },
    });
    expect(state.queue.followUp).toEqual(["第二句"]);
    expect(state.messages.at(-1)).toEqual(
      expect.objectContaining({ role: "user", content: "第一句" }),
    );
  });

  it("consumes one queue entry per message even when both queues hold the same text", () => {
    let state = apply(initialChatProtocolState, {
      type: "queue_update",
      steering: ["同样文本"],
      followUp: ["同样文本"],
    });

    state = apply(state, {
      type: "message_start",
      message: { role: "user", content: "同样文本" },
    });

    expect(state.queue).toEqual({ steering: [], followUp: ["同样文本"] });
    expect(state.messages).toHaveLength(1);
  });

  it("ignores the initial prompt echo that duplicates the optimistic user message", () => {
    let state = reduceChatProtocol(initialChatProtocolState, {
      type: "append_user",
      message: {
        id: "user-1",
        role: "user",
        content: "新提问",
        createdAt: "10:00:00",
      },
    });

    const echoed = apply(state, {
      type: "message_start",
      message: { role: "user", content: "新提问" },
    });

    expect(echoed).toBe(state);
    expect(echoed.messages.filter((item) => item.role === "user")).toHaveLength(1);
  });

  it("resets the queue when canonical history replaces the state", () => {
    let state = apply(initialChatProtocolState, {
      type: "queue_update",
      steering: ["残留"],
      followUp: [],
    });

    state = reduceChatProtocol(state, { type: "replace_history", messages: [] });

    expect(state.queue).toEqual({ steering: [], followUp: [] });
  });
});

describe("runtime notice (auto retry / compaction)", () => {
  it("sets the retry notice from auto_retry_start and clears it on success", () => {
    let state = apply(initialChatProtocolState, {
      type: "auto_retry_start",
      attempt: 2,
      maxAttempts: 5,
      delayMs: 3000,
      errorMessage: "429 rate limited",
    });

    expect(state.runtimeNotice).toEqual({
      kind: "retry",
      attempt: 2,
      maxAttempts: 5,
      delayMs: 3000,
      errorMessage: "429 rate limited",
    });

    state = apply(state, {
      type: "auto_retry_end",
      success: true,
      attempt: 2,
      finalError: null,
    });

    expect(state.runtimeNotice).toBeNull();
  });

  it("overwrites an earlier notice with a later one (单值)", () => {
    // 溢出恢复链的真实次序：compaction_start → compaction_started → auto_retry_start
    let state = apply(initialChatProtocolState, {
      type: "auto_retry_start",
      attempt: 1,
      maxAttempts: 1,
      delayMs: 0,
      errorMessage: "Context overflow",
    });
    state = apply(state, { type: "compaction_start", reason: "overflow" });
    expect(state.runtimeNotice).toEqual({ kind: "compaction", reason: "overflow" });

    state = apply(state, { type: "compaction_started", reason: "overflow" });
    expect(state.runtimeNotice).toEqual({ kind: "compaction", reason: "overflow" });

    state = apply(state, {
      type: "auto_retry_start",
      attempt: 1,
      maxAttempts: 1,
      delayMs: 0,
      errorMessage: "Context overflow",
    });
    expect(state.runtimeNotice).toEqual(
      expect.objectContaining({ kind: "retry", attempt: 1 }),
    );
  });

  it("clears the notice when retry ends in failure (错误由 failStreaming 呈现)", () => {
    let state = apply(initialChatProtocolState, {
      type: "auto_retry_start",
      attempt: 1,
      maxAttempts: 1,
      delayMs: 0,
      errorMessage: "Context overflow",
    });

    state = apply(state, {
      type: "auto_retry_end",
      success: false,
      attempt: 1,
      finalError: "still overflowing",
    });

    // 失败由 failStreaming 的错误卡片呈现；"重试中"状态条不得在流终止后挂死
    expect(state.runtimeNotice).toBeNull();
    expect(state.messages.at(-1)?.error).toBe("still overflowing");
    expect(state.isStreaming).toBe(false);
  });

  it("clears the compaction notice on core completed events (阈值压缩无应用级 end)", () => {
    let state = apply(initialChatProtocolState, {
      type: "compaction_started",
      reason: "threshold",
    });
    expect(state.runtimeNotice).toEqual({ kind: "compaction", reason: "threshold" });

    state = apply(state, {
      type: "compaction_completed",
      reason: "threshold",
      aborted: false,
    });
    expect(state.runtimeNotice).toBeNull();
  });

  it("clears the compaction notice on a clean compaction_end and on error", () => {
    let state = apply(initialChatProtocolState, {
      type: "compaction_start",
      reason: "overflow",
    });

    state = apply(state, {
      type: "compaction_end",
      reason: "overflow",
      aborted: false,
      willRetry: true,
      errorMessage: null,
    });
    expect(state.runtimeNotice).toBeNull();

    state = apply(state, { type: "compaction_start", reason: "overflow" });
    state = apply(state, {
      type: "compaction_end",
      reason: "overflow",
      aborted: true,
      willRetry: false,
      errorMessage: "compaction backend failed",
    });
    expect(state.runtimeNotice).toBeNull();
    expect(state.messages.at(-1)?.error).toBe("compaction backend failed");
  });

  it("clears a stale notice when the run settles (兜底，防事件丢失挂死)", () => {
    // compaction_started 后 completed 丢失的防御场景：Settled 终态兜底清除
    let state = apply(initialChatProtocolState, {
      type: "compaction_started",
      reason: "threshold",
    });
    state = apply(state, { type: "agent_settled" });

    expect(state.runtimeNotice).toBeNull();
    expect(state.isStreaming).toBe(false);
  });

  it("clears the notice when canonical history replaces the state", () => {
    let state = apply(initialChatProtocolState, {
      type: "auto_retry_start",
      attempt: 1,
      maxAttempts: 1,
      delayMs: 0,
      errorMessage: "Context overflow",
    });

    state = reduceChatProtocol(state, { type: "replace_history", messages: [] });

    expect(state.runtimeNotice).toBeNull();
  });
});

describe("local run metrics (steps / LLM / tool durations)", () => {
  it("counts turn steps and accumulates LLM durations across rounds", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    let state = apply(initialChatProtocolState, { type: "turn_start" });
    state = apply(state, { type: "message_start", message: emptyAssistant });

    now.mockReturnValue(4_000);
    state = apply(state, { type: "message_end", message: emptyAssistant });
    expect(state.metrics.steps).toBe(1);
    expect(state.metrics.llmMs).toBe(3_000);

    // 第二轮 LLM 调用：步数与耗时累计而非覆盖
    now.mockReturnValue(10_000);
    state = apply(state, { type: "turn_start" });
    state = apply(state, { type: "message_start", message: emptyAssistant });
    now.mockReturnValue(12_000);
    state = apply(state, { type: "message_end", message: emptyAssistant });

    expect(state.metrics.steps).toBe(2);
    expect(state.metrics.llmMs).toBe(5_000);
    expect(state.metrics.llmStartMs).toBeNull();
  });

  it("pairs tool durations by toolCallId for parallel executions", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(20_000);
    let state = apply(initialChatProtocolState, {
      type: "tool_execution_start",
      toolCallId: "call-a",
      toolName: "read_file",
      args: {},
    });
    now.mockReturnValue(21_000);
    state = apply(state, {
      type: "tool_execution_start",
      toolCallId: "call-b",
      toolName: "exec_command",
      args: {},
    });
    now.mockReturnValue(23_000);
    state = apply(state, {
      type: "tool_execution_end",
      toolCallId: "call-a",
      toolName: "read_file",
      result: { content: [], isError: false },
      isError: false,
    });
    now.mockReturnValue(26_000);
    state = apply(state, {
      type: "tool_execution_end",
      toolCallId: "call-b",
      toolName: "exec_command",
      result: { content: [], isError: false },
      isError: false,
    });

    // call-a 3s + call-b 5s，乱序返回不影响各自配对
    expect(state.metrics.toolMs).toBe(8_000);
    expect(state.metrics.toolStartMs).toEqual({});
  });

  it("ignores a tool_execution_end that has no tracked start", () => {
    const state = apply(initialChatProtocolState, {
      type: "tool_execution_end",
      toolCallId: "orphan",
      toolName: "read_file",
      result: { content: [], isError: false },
      isError: false,
    });

    expect(state.metrics.toolMs).toBe(0);
  });

  it("resets metrics when canonical history replaces the state", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    let state = apply(initialChatProtocolState, { type: "turn_start" });
    state = apply(state, { type: "message_start", message: emptyAssistant });
    now.mockReturnValue(2_000);
    state = apply(state, { type: "message_end", message: emptyAssistant });
    expect(state.metrics.steps).toBe(1);

    state = reduceChatProtocol(state, { type: "replace_history", messages: [] });

    expect(state.metrics).toEqual(emptyChatMetrics);
  });
});

describe("reasoning duration (thinking span tracking)", () => {
  it("writes accumulated thinking time onto the finalized assistant message", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    let state = apply(initialChatProtocolState, {
      type: "message_start",
      message: emptyAssistant,
    });
    state = apply(state, {
      type: "message_update",
      message: emptyAssistant,
      assistantMessageEvent: {
        type: "thinking_start",
        contentIndex: 0,
        partial: emptyAssistant,
      },
    });

    now.mockReturnValue(2_500);
    state = apply(state, {
      type: "message_update",
      message: emptyAssistant,
      assistantMessageEvent: {
        type: "thinking_end",
        contentIndex: 0,
        content: "thought",
        partial: emptyAssistant,
      },
    });

    state = apply(state, {
      type: "message_end",
      message: {
        ...emptyAssistant,
        content: [{ type: "thinking", thinking: "thought" }],
      },
    });

    expect(state.messages[0].reasoningDuration).toBe(1_500);
  });

  it("resets the accumulator for the next assistant message", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    let state = apply(initialChatProtocolState, {
      type: "message_start",
      message: emptyAssistant,
    });
    state = apply(state, {
      type: "message_update",
      message: emptyAssistant,
      assistantMessageEvent: {
        type: "thinking_start",
        contentIndex: 0,
        partial: emptyAssistant,
      },
    });
    now.mockReturnValue(3_000);
    state = apply(state, {
      type: "message_update",
      message: emptyAssistant,
      assistantMessageEvent: {
        type: "thinking_end",
        contentIndex: 0,
        content: "first",
        partial: emptyAssistant,
      },
    });
    state = apply(state, {
      type: "message_end",
      message: {
        ...emptyAssistant,
        content: [{ type: "thinking", thinking: "first" }],
      },
    });
    expect(state.messages[0].reasoningDuration).toBe(2_000);

    // 下一条消息未产生 thinking 事件：不继承上一条的累计值
    state = apply(state, { type: "message_start", message: emptyAssistant });
    state = apply(state, {
      type: "message_end",
      message: {
        ...emptyAssistant,
        content: [{ type: "text", text: "answer" }],
      },
    });

    expect(state.messages.at(-1)?.reasoningDuration).toBeUndefined();
  });
});

describe("formatRunDuration", () => {
  it("formats sub-minute durations with one decimal", () => {
    expect(formatRunDuration(0)).toBe("0.0s");
    expect(formatRunDuration(1_500)).toBe("1.5s");
    expect(formatRunDuration(59_949)).toBe("59.9s");
    // 59.95s+ 已按分钟进位，不得显示 "60.0s"
    expect(formatRunDuration(59_999)).toBe("1m0s");
  });

  it("carries seconds into minutes instead of rendering 1m60s", () => {
    expect(formatRunDuration(119_700)).toBe("2m0s");
    expect(formatRunDuration(60_000)).toBe("1m0s");
    expect(formatRunDuration(125_000)).toBe("2m5s");
  });
});
