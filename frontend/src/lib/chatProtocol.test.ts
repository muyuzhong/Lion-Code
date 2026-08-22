import { describe, expect, it } from "vitest";

import {
  actionForInput,
  decodeServerEvent,
  initialChatProtocolState,
  reduceChatProtocol,
  type ChatProtocolState,
  type ServerEvent,
} from "./chatProtocol";

function apply(state: ChatProtocolState, event: ServerEvent) {
  return reduceChatProtocol(state, { type: "server_event", event });
}

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
