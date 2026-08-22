import type {
  ChatMessage,
  ConfirmRequest,
  PlanApprovalRequest,
  ToolCallItem,
} from "@/types/chat";

export type PlanApprovalChoice =
  | "clear-and-execute"
  | "execute"
  | "manual-execute"
  | "keep-planning";

export type ClientAction =
  | { action: "prompt"; prompt: string }
  | { action: "steer"; prompt: string }
  | { action: "follow_up"; prompt: string }
  | { action: "continue" }
  | { action: "compact" }
  | { action: "cancel" }
  | { action: "command"; command: string }
  | { action: "confirm_response"; requestId: string; approved: boolean }
  | {
      action: "plan_approval_response";
      requestId: string;
      choice: PlanApprovalChoice;
      feedback?: string;
    };

type TextContent = { type: "text"; text: string };
type ThinkingContent = { type: "thinking"; thinking: string };
type ImageContent = { type: "image"; data: string; mimeType: string };
type ToolCallContent = {
  type: "toolCall";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};
type AssistantContent = TextContent | ThinkingContent | ToolCallContent;

type AssistantMessage = {
  role: "assistant";
  content: AssistantContent[];
  stopReason: "stop" | "length" | "toolUse" | "error" | "aborted";
  errorMessage: string | null;
};

type WireMessage =
  | AssistantMessage
  | { role: "user"; content: string | Array<TextContent | ImageContent> }
  | {
      role: "toolResult";
      toolCallId: string;
      toolName: string;
      content: Array<TextContent | ImageContent>;
      isError: boolean;
    }
  | {
      role: "custom";
      customType: string;
      content: string | Array<TextContent | ImageContent>;
    };

type AgentToolResult = {
  content: Array<TextContent | ImageContent>;
  isError: boolean;
};

type AssistantMessageEvent =
  | { type: "start"; partial: AssistantMessage }
  | {
      type: "text_start" | "thinking_start" | "toolcall_start";
      contentIndex: number;
      partial: AssistantMessage;
    }
  | {
      type: "text_delta" | "thinking_delta" | "toolcall_delta";
      contentIndex: number;
      delta: string;
      partial: AssistantMessage;
    }
  | {
      type: "text_end" | "thinking_end";
      contentIndex: number;
      content: string;
      partial: AssistantMessage;
    }
  | {
      type: "toolcall_end";
      contentIndex: number;
      toolCall: ToolCallContent;
      partial: AssistantMessage;
    }
  | {
      type: "done";
      reason: "stop" | "length" | "toolUse";
      message: AssistantMessage;
    }
  | {
      type: "error";
      reason: "error" | "aborted";
      error: AssistantMessage;
    };

export type ServerEvent =
  | { type: "agent_start" | "agent_end" | "turn_start" }
  | { type: "turn_end"; message: WireMessage; toolResults: WireMessage[] }
  | { type: "message_start"; message: WireMessage }
  | {
      type: "message_update";
      message: WireMessage;
      assistantMessageEvent: AssistantMessageEvent;
    }
  | { type: "message_end" | "turn_failed"; message: WireMessage }
  | {
      type: "tool_execution_start";
      toolCallId: string;
      toolName: string;
      args: Record<string, unknown>;
    }
  | {
      type: "tool_execution_update";
      toolCallId: string;
      toolName: string;
      args: Record<string, unknown>;
      partialResult: AgentToolResult;
    }
  | {
      type: "tool_execution_end";
      toolCallId: string;
      toolName: string;
      result: AgentToolResult;
      isError: boolean;
    }
  | { type: "cancelled"; message?: WireMessage | null }
  | { type: "session_agent_end"; willRetry: boolean }
  | { type: "agent_settled" }
  | { type: "queue_update"; steering: string[]; followUp: string[] }
  | { type: "compaction_started"; reason: CompactionReason }
  | {
      type: "compaction_completed";
      reason: CompactionReason;
      aborted: boolean;
    }
  | { type: "compaction_start"; reason: CompactionReason }
  | {
      type: "compaction_end";
      reason: string;
      aborted: boolean;
      willRetry: boolean;
      errorMessage?: string | null;
    }
  | {
      type: "auto_retry_start";
      attempt: number;
      maxAttempts: number;
      delayMs: number;
      errorMessage: string;
    }
  | {
      type: "auto_retry_end";
      success: boolean;
      attempt: number;
      finalError?: string | null;
    }
  | { type: "confirm_request"; requestId: string; message: string }
  | { type: "plan_approval_request"; requestId: string; plan: string }
  | { type: "notice"; text: string; role: "info" | "error" | "status" }
  | { type: "server_error" | "protocol_error"; message: string };

type CompactionReason = "manual" | "threshold" | "overflow";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isCompactionReason(value: unknown): value is CompactionReason {
  return value === "manual" || value === "threshold" || value === "overflow";
}

function isTextContent(value: unknown): value is TextContent {
  return isRecord(value) && value.type === "text" && typeof value.text === "string";
}

function isImageContent(value: unknown): value is ImageContent {
  return (
    isRecord(value) &&
    value.type === "image" &&
    typeof value.data === "string" &&
    typeof value.mimeType === "string"
  );
}

function isToolCallContent(value: unknown): value is ToolCallContent {
  return (
    isRecord(value) &&
    value.type === "toolCall" &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    isRecord(value.arguments)
  );
}

function isAssistantMessage(value: unknown): value is AssistantMessage {
  if (!isRecord(value) || value.role !== "assistant" || !Array.isArray(value.content)) {
    return false;
  }
  const validStopReason =
    value.stopReason === "stop" ||
    value.stopReason === "length" ||
    value.stopReason === "toolUse" ||
    value.stopReason === "error" ||
    value.stopReason === "aborted";
  return (
    validStopReason &&
    isNullableString(value.errorMessage) &&
    value.content.every(
      (block) =>
        isTextContent(block) ||
        (isRecord(block) &&
          block.type === "thinking" &&
          typeof block.thinking === "string") ||
        isToolCallContent(block),
    )
  );
}

function isVisibleContent(value: unknown): boolean {
  return (
    typeof value === "string" ||
    (Array.isArray(value) &&
      value.every((block) => isTextContent(block) || isImageContent(block)))
  );
}

function isWireMessage(value: unknown): value is WireMessage {
  if (!isRecord(value) || typeof value.role !== "string") return false;
  if (value.role === "assistant") return isAssistantMessage(value);
  if (value.role === "user") return isVisibleContent(value.content);
  if (value.role === "toolResult") {
    return (
      typeof value.toolCallId === "string" &&
      typeof value.toolName === "string" &&
      Array.isArray(value.content) &&
      value.content.every(
        (block) => isTextContent(block) || isImageContent(block),
      ) &&
      typeof value.isError === "boolean"
    );
  }
  return (
    value.role === "custom" &&
    typeof value.customType === "string" &&
    isVisibleContent(value.content)
  );
}

function isAgentToolResult(value: unknown): value is AgentToolResult {
  return (
    isRecord(value) &&
    Array.isArray(value.content) &&
    value.content.every(
      (block) => isTextContent(block) || isImageContent(block),
    ) &&
    typeof value.isError === "boolean"
  );
}

function isAssistantMessageEvent(value: unknown): value is AssistantMessageEvent {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  if (value.type === "start") return isAssistantMessage(value.partial);
  if (
    value.type === "text_start" ||
    value.type === "thinking_start" ||
    value.type === "toolcall_start"
  ) {
    return typeof value.contentIndex === "number" && isAssistantMessage(value.partial);
  }
  if (
    value.type === "text_delta" ||
    value.type === "thinking_delta" ||
    value.type === "toolcall_delta"
  ) {
    return (
      typeof value.contentIndex === "number" &&
      typeof value.delta === "string" &&
      isAssistantMessage(value.partial)
    );
  }
  if (value.type === "text_end" || value.type === "thinking_end") {
    return (
      typeof value.contentIndex === "number" &&
      typeof value.content === "string" &&
      isAssistantMessage(value.partial)
    );
  }
  if (value.type === "toolcall_end") {
    return (
      typeof value.contentIndex === "number" &&
      isToolCallContent(value.toolCall) &&
      isAssistantMessage(value.partial)
    );
  }
  if (value.type === "done") {
    return (
      (value.reason === "stop" ||
        value.reason === "length" ||
        value.reason === "toolUse") &&
      isAssistantMessage(value.message)
    );
  }
  return (
    value.type === "error" &&
    (value.reason === "error" || value.reason === "aborted") &&
    isAssistantMessage(value.error)
  );
}

export function decodeServerEvent(value: unknown): ServerEvent | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  let valid = false;
  switch (value.type) {
    case "agent_start":
    case "agent_end":
    case "turn_start":
    case "agent_settled":
      valid = true;
      break;
    case "turn_end":
      valid =
        isWireMessage(value.message) &&
        Array.isArray(value.toolResults) &&
        value.toolResults.every(isWireMessage);
      break;
    case "message_start":
    case "message_end":
    case "turn_failed":
      valid = isWireMessage(value.message);
      break;
    case "message_update":
      valid =
        isWireMessage(value.message) &&
        isAssistantMessageEvent(value.assistantMessageEvent);
      break;
    case "tool_execution_start":
      valid =
        typeof value.toolCallId === "string" &&
        typeof value.toolName === "string" &&
        isRecord(value.args);
      break;
    case "tool_execution_update":
      valid =
        typeof value.toolCallId === "string" &&
        typeof value.toolName === "string" &&
        isRecord(value.args) &&
        isAgentToolResult(value.partialResult);
      break;
    case "tool_execution_end":
      valid =
        typeof value.toolCallId === "string" &&
        typeof value.toolName === "string" &&
        isAgentToolResult(value.result) &&
        typeof value.isError === "boolean";
      break;
    case "cancelled":
      valid = value.message === null || isWireMessage(value.message);
      break;
    case "session_agent_end":
      valid = typeof value.willRetry === "boolean";
      break;
    case "queue_update":
      valid = isStringArray(value.steering) && isStringArray(value.followUp);
      break;
    case "compaction_started":
    case "compaction_start":
      valid = isCompactionReason(value.reason);
      break;
    case "compaction_completed":
      valid =
        isCompactionReason(value.reason) && typeof value.aborted === "boolean";
      break;
    case "compaction_end":
      valid =
        isCompactionReason(value.reason) &&
        typeof value.aborted === "boolean" &&
        typeof value.willRetry === "boolean" &&
        isNullableString(value.errorMessage);
      break;
    case "auto_retry_start":
      valid =
        typeof value.attempt === "number" &&
        typeof value.maxAttempts === "number" &&
        typeof value.delayMs === "number" &&
        typeof value.errorMessage === "string";
      break;
    case "auto_retry_end":
      valid =
        typeof value.success === "boolean" &&
        typeof value.attempt === "number" &&
        isNullableString(value.finalError);
      break;
    case "confirm_request":
      valid =
        typeof value.requestId === "string" && typeof value.message === "string";
      break;
    case "plan_approval_request":
      valid =
        typeof value.requestId === "string" && typeof value.plan === "string";
      break;
    case "notice":
      valid =
        typeof value.text === "string" &&
        (value.role === "info" || value.role === "error" || value.role === "status");
      break;
    case "server_error":
    case "protocol_error":
      valid = typeof value.message === "string";
      break;
  }
  return valid ? (value as ServerEvent) : null;
}

// steering / followUp 队列的文本快照，与后端 queue_update 事件字段一一对应
export interface ChatQueueState {
  steering: string[];
  followUp: string[];
}

const emptyChatQueue: ChatQueueState = { steering: [], followUp: [] };

// 运行状态条（单值，后到覆盖先到）：自动重试 / 上下文压缩的进行中提示。
// 成功或完成事件清除；失败与流终止也清除——错误由 failStreaming 的消息卡片
// 呈现，保留"重试中/压缩中"会与已终止的流矛盾且永不消失。
export type RuntimeNotice =
  | {
      kind: "retry";
      attempt: number;
      maxAttempts: number;
      delayMs: number;
      errorMessage: string;
    }
  | { kind: "compaction"; reason: CompactionReason };

// 本地打点指标（D11：无 per-request usage，只做耗时类）。
// 协议事件不带服务端时间戳，llmMs / toolMs 以 reducer 收到事件的本地时钟近似。
// llmStartMs / toolStartMs 是进行中的计时起点，仅供 reducer 配对，不参与展示。
export interface ChatMetrics {
  steps: number; // turn_start 计数：每个 LLM 调用轮计一步
  llmMs: number; // assistant message_start→message_end 累计
  toolMs: number; // tool_execution_start→end 累计（按 toolCallId 配对）
  llmStartMs: number | null;
  toolStartMs: Record<string, number>;
}

export const emptyChatMetrics: ChatMetrics = {
  steps: 0,
  llmMs: 0,
  toolMs: 0,
  llmStartMs: null,
  toolStartMs: {},
};

export interface ChatProtocolState {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentAssistantId: string | null;
  nextAssistantSequence: number;
  confirmRequest: ConfirmRequest | null;
  planApprovalRequest: PlanApprovalRequest | null;
  queue: ChatQueueState;
  runtimeNotice: RuntimeNotice | null;
  metrics: ChatMetrics;
  // 思考耗时（D12）的本地计时：thinking 块 start/end 在 reducer 配对，
  // 累计值在 message_end 写入 ChatMessage.reasoningDuration；新消息开始时归零
  thinkingStartMs: number | null;
  reasoningElapsedMs: number;
}

export const initialChatProtocolState: ChatProtocolState = {
  messages: [],
  isStreaming: false,
  currentAssistantId: null,
  nextAssistantSequence: 1,
  confirmRequest: null,
  planApprovalRequest: null,
  queue: emptyChatQueue,
  runtimeNotice: null,
  metrics: emptyChatMetrics,
  thinkingStartMs: null,
  reasoningElapsedMs: 0,
};

export type ChatProtocolAction =
  | { type: "server_event"; event: ServerEvent }
  | { type: "replace_history"; messages: ChatMessage[] }
  | { type: "append_user"; message: ChatMessage }
  | { type: "run_requested" }
  | { type: "disconnected" }
  | { type: "clear_confirm" }
  | { type: "clear_plan_approval" };

export function reduceChatProtocol(
  state: ChatProtocolState,
  action: ChatProtocolAction,
): ChatProtocolState {
  switch (action.type) {
    case "replace_history":
      return {
        ...state,
        messages: action.messages,
        isStreaming: false,
        currentAssistantId: null,
        confirmRequest: null,
        planApprovalRequest: null,
        // 队列是服务端瞬态状态，不在 canonical history 内；重连/换会话后等下一次 queue_update 同步
        queue: emptyChatQueue,
        // 本地打点与进行中提示同样不跨会话/重连累计
        runtimeNotice: null,
        metrics: emptyChatMetrics,
        thinkingStartMs: null,
        reasoningElapsedMs: 0,
      };
    case "append_user":
      return {
        ...state,
        messages: [...state.messages, action.message],
        isStreaming: true,
      };
    case "run_requested":
      return { ...state, isStreaming: true };
    case "disconnected": {
      const disconnected = finalizeStreaming(state);
      return {
        ...disconnected,
        confirmRequest: null,
        planApprovalRequest: null,
      };
    }
    case "clear_confirm":
      return { ...state, confirmRequest: null };
    case "clear_plan_approval":
      return { ...state, planApprovalRequest: null };
    case "server_event":
      return reduceServerEvent(state, action.event);
  }
}

function reduceServerEvent(
  state: ChatProtocolState,
  event: ServerEvent,
): ChatProtocolState {
  switch (event.type) {
    case "agent_start":
      return { ...state, isStreaming: true };
    case "message_start":
      if (event.message.role === "assistant") {
        return startAssistantMessage(trackLlmStart(state), event.message);
      }
      if (event.message.role === "user") {
        return consumeQueuedUserMessage(state, event.message);
      }
      return state;
    case "message_update": {
      const delta = event.assistantMessageEvent;
      if (delta.type === "error") {
        return applyAssistantError(state, delta.error);
      }
      if (delta.type === "thinking_start" || delta.type === "thinking_end") {
        return trackThinkingSpan(state, delta.type === "thinking_start");
      }
      if (delta.type !== "text_delta" && delta.type !== "thinking_delta") {
        return state;
      }
      const [next, assistantId] = ensureAssistantMessage(state);
      return updateMessage(next, assistantId, (message) =>
        delta.type === "text_delta"
          ? { ...message, content: message.content + delta.delta }
          : { ...message, reasoning: (message.reasoning ?? "") + delta.delta },
      );
    }
    case "message_end":
      return event.message.role === "assistant"
        ? finalizeAssistantMessage(trackLlmEnd(state), event.message)
        : state;
    case "turn_failed":
      return event.message.role === "assistant"
        ? applyAssistantError(state, event.message)
        : failStreaming(state, "Agent turn failed.");
    case "tool_execution_start":
      return updateTool(
        trackToolStart(state, event.toolCallId),
        event.toolCallId,
        () => ({
          id: event.toolCallId,
          toolName: event.toolName,
          args: event.args,
          status: "running",
        }),
      );
    case "tool_execution_update":
      return updateTool(state, event.toolCallId, (current) => ({
        ...current,
        id: event.toolCallId,
        toolName: event.toolName,
        args: event.args,
        status: "running",
        result: toolResultText(event.partialResult),
      }));
    case "tool_execution_end":
      return updateTool(
        trackToolEnd(state, event.toolCallId),
        event.toolCallId,
        (current) => ({
          ...current,
          id: event.toolCallId,
          toolName: event.toolName,
          status: event.isError ? "error" : "completed",
          result: toolResultText(event.result),
        }),
      );
    case "confirm_request":
      return {
        ...state,
        confirmRequest: { requestId: event.requestId, message: event.message },
      };
    case "queue_update":
      // 后端只保证全量快照（无逐项增量事件），直接替换才能维持单一事实源
      return {
        ...state,
        queue: { steering: event.steering, followUp: event.followUp },
      };
    case "plan_approval_request":
      return {
        ...state,
        planApprovalRequest: { requestId: event.requestId, plan: event.plan },
      };
    case "server_error":
    case "protocol_error":
      return failStreaming(state, event.message);
    // 压缩/重试的失败走 failStreaming（内部清除状态条）：错误由消息卡片呈现，
    // 状态条只在事件流进行中有意义
    case "compaction_end":
      return event.errorMessage
        ? failStreaming(state, event.errorMessage)
        : { ...state, runtimeNotice: null };
    case "auto_retry_end":
      return !event.success && event.finalError
        ? failStreaming(state, event.finalError)
        : { ...state, runtimeNotice: null };
    case "cancelled":
    case "agent_settled":
      return finalizeStreaming(state);
    case "auto_retry_start":
      return {
        ...state,
        runtimeNotice: {
          kind: "retry",
          attempt: event.attempt,
          maxAttempts: event.maxAttempts,
          delayMs: event.delayMs,
          errorMessage: event.errorMessage,
        },
      };
    case "compaction_start":
    case "compaction_started":
      return {
        ...state,
        runtimeNotice: { kind: "compaction", reason: event.reason },
      };
    case "compaction_completed":
      // 阈值压缩只发核心级 started/completed（无应用级 compaction_end），
      // 必须在此清除，否则状态条挂到会话结束
      return { ...state, runtimeNotice: null };
    // turn_start 计步：core loop 每个 LLM 调用轮发一次 turn_start
    case "turn_start":
      return { ...state, metrics: stepMetrics(state.metrics) };
    case "agent_end":
    case "turn_end":
    case "session_agent_end":
    case "notice":
      return state;
  }
}

// 排队消息被后端消费时以 user 角色 message_start 入流；后端在消费时不发
// queue_update，前端须在入流的同时本地移除对应队列项，否则徽标永不消失。
// 初始 prompt 的 message_start 是服务端回显，本地已乐观 append，按队列文本
// 匹配不到时直接忽略，避免重复入流。
function consumeQueuedUserMessage(
  state: ChatProtocolState,
  message: WireMessage & { role: "user" },
): ChatProtocolState {
  const text = userContentText(message.content);
  const steeringIndex = state.queue.steering.indexOf(text);
  const followUpIndex = state.queue.followUp.indexOf(text);
  if (steeringIndex === -1 && followUpIndex === -1) return state;

  // 一次消费只移除一个队列项；steering 优先（后端消费顺序：steering 先于 follow_up）
  const queue: ChatQueueState = {
    steering:
      steeringIndex === -1
        ? state.queue.steering
        : state.queue.steering.filter((_, index) => index !== steeringIndex),
    followUp:
      steeringIndex !== -1 || followUpIndex === -1
        ? state.queue.followUp
        : state.queue.followUp.filter((_, index) => index !== followUpIndex),
  };
  const id = `user-live-${state.nextAssistantSequence}`;
  return {
    ...state,
    queue,
    nextAssistantSequence: state.nextAssistantSequence + 1,
    messages: [
      ...state.messages,
      { id, role: "user" as const, content: text },
    ],
  };
}

function userContentText(
  content: string | Array<TextContent | ImageContent>,
): string {
  return typeof content === "string"
    ? content
    : content
        .filter((block): block is TextContent => block.type === "text")
        .map((block) => block.text)
        .join("");
}

// ─── 本地打点：协议事件无时间戳，以 reducer 收到时刻近似 ───

// assistant message_start 无条件覆盖计时起点：上一条消息若经错误路径结束
// （无 message_end），残留的旧起点会把间隔错误计入下一条消息
function trackLlmStart(state: ChatProtocolState): ChatProtocolState {
  return { ...state, metrics: { ...state.metrics, llmStartMs: Date.now() } };
}

function trackLlmEnd(state: ChatProtocolState): ChatProtocolState {
  const { llmStartMs } = state.metrics;
  if (llmStartMs === null) return state;
  return {
    ...state,
    metrics: {
      ...state.metrics,
      llmMs: state.metrics.llmMs + (Date.now() - llmStartMs),
      llmStartMs: null,
    },
  };
}

function trackToolStart(
  state: ChatProtocolState,
  toolCallId: string,
): ChatProtocolState {
  return {
    ...state,
    metrics: {
      ...state.metrics,
      toolStartMs: { ...state.metrics.toolStartMs, [toolCallId]: Date.now() },
    },
  };
}

// 乱序或缺失 start 的 end 事件不计时，避免负值/空指针
function trackToolEnd(
  state: ChatProtocolState,
  toolCallId: string,
): ChatProtocolState {
  const started = state.metrics.toolStartMs[toolCallId];
  if (started === undefined) return state;
  const toolStartMs = { ...state.metrics.toolStartMs };
  delete toolStartMs[toolCallId];
  return {
    ...state,
    metrics: {
      ...state.metrics,
      toolMs: state.metrics.toolMs + (Date.now() - started),
      toolStartMs,
    },
  };
}

function stepMetrics(metrics: ChatMetrics): ChatMetrics {
  return { ...metrics, steps: metrics.steps + 1 };
}

// 思考块计时：同一消息内多个 thinking 块顺序累计，
// message_end 时由 finalizeAssistantMessage 写入 reasoningDuration
function trackThinkingSpan(
  state: ChatProtocolState,
  isStart: boolean,
): ChatProtocolState {
  if (isStart) {
    return state.thinkingStartMs === null
      ? { ...state, thinkingStartMs: Date.now() }
      : state;
  }
  if (state.thinkingStartMs === null) return state;
  return {
    ...state,
    thinkingStartMs: null,
    reasoningElapsedMs:
      state.reasoningElapsedMs + (Date.now() - state.thinkingStartMs),
  };
}

function startAssistantMessage(
  state: ChatProtocolState,
  message: AssistantMessage,
): ChatProtocolState {
  const current = state.messages.find(
    (item) => item.id === state.currentAssistantId,
  );
  if (current?.isStreaming) return state;

  const [next, assistantId] = ensureAssistantMessage({
    ...state,
    currentAssistantId: null,
  });
  return updateMessage(next, assistantId, (item) => ({
    ...item,
    content: assistantText(message),
    reasoning: assistantThinking(message),
  }));
}

function ensureAssistantMessage(
  state: ChatProtocolState,
): [ChatProtocolState, string] {
  if (
    state.currentAssistantId &&
    state.messages.some((message) => message.id === state.currentAssistantId)
  ) {
    return [state, state.currentAssistantId];
  }

  const assistantId = `live-${state.nextAssistantSequence}`;
  return [
    {
      ...state,
      currentAssistantId: assistantId,
      nextAssistantSequence: state.nextAssistantSequence + 1,
      isStreaming: true,
      // 新消息开始：清空上一条消息遗留的思考计时
      thinkingStartMs: null,
      reasoningElapsedMs: 0,
      messages: [
        ...state.messages,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          reasoning: "",
          tools: [],
          isStreaming: true,
        },
      ],
    },
    assistantId,
  ];
}

function finalizeAssistantMessage(
  state: ChatProtocolState,
  wireMessage: AssistantMessage,
): ChatProtocolState {
  const [next, assistantId] = ensureAssistantMessage(state);
  const terminalError =
    wireMessage.stopReason === "error" || wireMessage.stopReason === "aborted"
      ? wireMessage.errorMessage || `Assistant ${wireMessage.stopReason}.`
      : undefined;
  const canonicalTools = wireMessage.content
    .filter((block): block is ToolCallContent => block.type === "toolCall")
    .map<ToolCallItem>((block) => ({
      id: block.id,
      toolName: block.name,
      args: block.arguments,
      status: "running",
    }));

  const updated = updateMessage(next, assistantId, (message) => ({
    ...message,
    content: assistantText(wireMessage),
    reasoning: assistantThinking(wireMessage),
    tools: mergeTools(message.tools ?? [], canonicalTools),
    error: terminalError,
    isStreaming: false,
    // 本条消息累计的思考耗时（历史消息无此数据，保持缺省）
    reasoningDuration:
      next.reasoningElapsedMs > 0
        ? next.reasoningElapsedMs
        : message.reasoningDuration,
  }));
  return terminalError ? { ...updated, isStreaming: false } : updated;
}

function applyAssistantError(
  state: ChatProtocolState,
  message: AssistantMessage,
): ChatProtocolState {
  return failStreaming(
    finalizeAssistantMessage(state, message),
    message.errorMessage || "Assistant provider error.",
  );
}

function failStreaming(
  state: ChatProtocolState,
  error: string,
): ChatProtocolState {
  const [next, assistantId] = ensureAssistantMessage(state);
  const failed = updateMessage(next, assistantId, (message) => ({
    ...message,
    error,
    isStreaming: false,
  }));
  // 流失败即终止："重试中/压缩中"状态条不得在失败后继续显示
  return {
    ...failed,
    isStreaming: false,
    currentAssistantId: null,
    runtimeNotice: null,
  };
}

function finalizeStreaming(state: ChatProtocolState): ChatProtocolState {
  const messages = state.messages.map((message) =>
    message.id === state.currentAssistantId
      ? { ...message, isStreaming: false }
      : message,
  );
  return {
    ...state,
    messages,
    isStreaming: false,
    currentAssistantId: null,
    // 兜底清除：正常链路由 end/completed 事件清除，此处防御事件丢失导致的挂死
    runtimeNotice: null,
  };
}

function updateTool(
  state: ChatProtocolState,
  toolCallId: string,
  update: (current: ToolCallItem) => ToolCallItem,
): ChatProtocolState {
  const [next, assistantId] = ensureAssistantMessage(state);
  return updateMessage(next, assistantId, (message) => {
    const tools = message.tools ?? [];
    const existing = tools.find((tool) => tool.id === toolCallId);
    const updatedTool = update(
      existing ?? {
        id: toolCallId,
        toolName: "Tool",
        status: "running",
      },
    );
    return {
      ...message,
      tools: existing
        ? tools.map((tool) => (tool.id === toolCallId ? updatedTool : tool))
        : [...tools, updatedTool],
    };
  });
}

function updateMessage(
  state: ChatProtocolState,
  messageId: string,
  update: (message: ChatMessage) => ChatMessage,
): ChatProtocolState {
  return {
    ...state,
    messages: state.messages.map((message) =>
      message.id === messageId ? update(message) : message,
    ),
  };
}

function mergeTools(
  current: ToolCallItem[],
  canonical: ToolCallItem[],
): ToolCallItem[] {
  const canonicalIds = new Set(canonical.map((tool) => tool.id));
  return [
    ...canonical.map(
      (tool) => current.find((item) => item.id === tool.id) ?? tool,
    ),
    ...current.filter((tool) => !canonicalIds.has(tool.id)),
  ];
}

function assistantText(message: AssistantMessage): string {
  return message.content
    .filter((block): block is TextContent => block.type === "text")
    .map((block) => block.text)
    .join("");
}

function assistantThinking(message: AssistantMessage): string {
  return message.content
    .filter((block): block is ThinkingContent => block.type === "thinking")
    .map((block) => block.thinking)
    .join("");
}

export function toolResultText(result: AgentToolResult): string {
  return result.content
    .filter((block): block is TextContent => block.type === "text")
    .map((block) => block.text)
    .join("");
}

// 统计行 / 思考耗时共用的时长格式化：<60s 一位小数秒，否则整秒进位后的 m+s。
// 以十分之一秒整数计数，避免 toFixed/round 在 59.95s+ 产出 "60.0s"/"1m60s"
export function formatRunDuration(ms: number): string {
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1)}s`;
  const totalSeconds = Math.round(tenths / 10);
  return `${Math.floor(totalSeconds / 60)}m${totalSeconds % 60}s`;
}

export function actionForInput(input: string): ClientAction | null {
  const text = input.trim();
  if (!text) return null;
  if (text === "/continue") return { action: "continue" };
  if (text === "/compact") return { action: "compact" };
  if (text.startsWith("/")) return { action: "command", command: text };
  return { action: "prompt", prompt: text };
}
