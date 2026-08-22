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

export interface ChatProtocolState {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentAssistantId: string | null;
  nextAssistantSequence: number;
  confirmRequest: ConfirmRequest | null;
  planApprovalRequest: PlanApprovalRequest | null;
  queue: ChatQueueState;
}

export const initialChatProtocolState: ChatProtocolState = {
  messages: [],
  isStreaming: false,
  currentAssistantId: null,
  nextAssistantSequence: 1,
  confirmRequest: null,
  planApprovalRequest: null,
  queue: emptyChatQueue,
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
        return startAssistantMessage(state, event.message);
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
        ? finalizeAssistantMessage(state, event.message)
        : state;
    case "turn_failed":
      return event.message.role === "assistant"
        ? applyAssistantError(state, event.message)
        : failStreaming(state, "Agent turn failed.");
    case "tool_execution_start":
      return updateTool(state, event.toolCallId, () => ({
        id: event.toolCallId,
        toolName: event.toolName,
        args: event.args,
        status: "running",
      }));
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
      return updateTool(state, event.toolCallId, (current) => ({
        ...current,
        id: event.toolCallId,
        toolName: event.toolName,
        status: event.isError ? "error" : "completed",
        result: toolResultText(event.result),
      }));
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
    case "compaction_end":
      return event.errorMessage
        ? failStreaming(state, event.errorMessage)
        : state;
    case "auto_retry_end":
      return !event.success && event.finalError
        ? failStreaming(state, event.finalError)
        : state;
    case "cancelled":
    case "agent_settled":
      return finalizeStreaming(state);
    case "agent_end":
    case "turn_start":
    case "turn_end":
    case "session_agent_end":
    case "compaction_started":
    case "compaction_completed":
    case "compaction_start":
    case "auto_retry_start":
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
  return { ...failed, isStreaming: false, currentAssistantId: null };
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

export function actionForInput(input: string): ClientAction | null {
  const text = input.trim();
  if (!text) return null;
  if (text === "/continue") return { action: "continue" };
  if (text === "/compact") return { action: "compact" };
  if (text.startsWith("/")) return { action: "command", command: text };
  return { action: "prompt", prompt: text };
}
