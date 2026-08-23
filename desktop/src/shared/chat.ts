/** Lion REST / WebSocket 与 Renderer 共享的聊天协议契约。 */

export type PlanApprovalChoice =
  | "clear-and-execute"
  | "execute"
  | "manual-execute"
  | "keep-planning";

export type ClientAction =
  | { action: "prompt"; prompt: string }
  | { action: "steer"; prompt: string }
  | { action: "follow_up"; prompt: string }
  | { action: "continue" | "compact" | "cancel" }
  | { action: "command"; command: string }
  | { action: "confirm_response"; requestId: string; approved: boolean }
  | {
      action: "plan_approval_response";
      requestId: string;
      choice: PlanApprovalChoice;
      feedback?: string;
    };

export interface ToolCallItem {
  id: string;
  toolName: string;
  args?: Record<string, unknown> | string;
  status: "running" | "completed" | "error";
  result?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  reasoningDuration?: number;
  tools?: ToolCallItem[];
  error?: string;
  isStreaming?: boolean;
  createdAt?: string | null;
}

type TextContent = { type: "text"; text: string };
type ImageContent = { type: "image"; data: string; mimeType: string };
type ToolCallContent = {
  type: "toolCall";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};
type AssistantMessage = {
  role: "assistant";
  content: Array<TextContent | { type: "thinking"; thinking: string } | ToolCallContent>;
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
  | { role: "custom"; customType: string; content: string | Array<TextContent | ImageContent> };
type AgentToolResult = { content: Array<TextContent | ImageContent>; isError: boolean };
type AssistantMessageEvent =
  | { type: "start"; partial: AssistantMessage }
  | { type: "text_start" | "thinking_start" | "toolcall_start"; contentIndex: number; partial: AssistantMessage }
  | { type: "text_delta" | "thinking_delta" | "toolcall_delta"; contentIndex: number; delta: string; partial: AssistantMessage }
  | { type: "text_end" | "thinking_end"; contentIndex: number; content: string; partial: AssistantMessage }
  | { type: "toolcall_end"; contentIndex: number; toolCall: ToolCallContent; partial: AssistantMessage }
  | { type: "done"; reason: "stop" | "length" | "toolUse"; message: AssistantMessage }
  | { type: "error"; reason: "error" | "aborted"; error: AssistantMessage };

type CompactionReason = "manual" | "threshold" | "overflow";

export type ServerEvent =
  | { type: "agent_start" | "agent_end" | "turn_start" | "agent_settled" }
  | { type: "turn_end"; message: WireMessage; toolResults: WireMessage[] }
  | { type: "message_start" | "message_end" | "turn_failed"; message: WireMessage }
  | { type: "message_update"; message: WireMessage; assistantMessageEvent: AssistantMessageEvent }
  | { type: "tool_execution_start"; toolCallId: string; toolName: string; args: Record<string, unknown> }
  | { type: "tool_execution_update"; toolCallId: string; toolName: string; args: Record<string, unknown>; partialResult: AgentToolResult }
  | { type: "tool_execution_end"; toolCallId: string; toolName: string; result: AgentToolResult; isError: boolean }
  | { type: "cancelled"; message?: WireMessage | null }
  | { type: "session_agent_end"; willRetry: boolean }
  | { type: "queue_update"; steering: string[]; followUp: string[] }
  | { type: "compaction_started" | "compaction_start"; reason: CompactionReason }
  | { type: "compaction_completed"; reason: CompactionReason; aborted: boolean }
  | { type: "compaction_end"; reason: CompactionReason; aborted: boolean; willRetry: boolean; errorMessage?: string | null }
  | { type: "auto_retry_start"; attempt: number; maxAttempts: number; delayMs: number; errorMessage: string }
  | { type: "auto_retry_end"; success: boolean; attempt: number; finalError?: string | null }
  | { type: "confirm_request"; requestId: string; message: string }
  | { type: "plan_approval_request"; requestId: string; plan: string }
  | { type: "notice"; text: string; role: "info" | "error" | "status" }
  | { type: "server_error" | "protocol_error"; message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");
const isNullableString = (value: unknown): value is string | null =>
  value === null || typeof value === "string";
const isCompactionReason = (value: unknown): value is CompactionReason =>
  value === "manual" || value === "threshold" || value === "overflow";
const isTextContent = (value: unknown): value is TextContent =>
  isRecord(value) && value.type === "text" && typeof value.text === "string";
const isImageContent = (value: unknown): value is ImageContent =>
  isRecord(value) && value.type === "image" && typeof value.data === "string" && typeof value.mimeType === "string";
const isToolCallContent = (value: unknown): value is ToolCallContent =>
  isRecord(value) && value.type === "toolCall" && typeof value.id === "string" && typeof value.name === "string" && isRecord(value.arguments);

function isAssistantMessage(value: unknown): value is AssistantMessage {
  if (!isRecord(value) || value.role !== "assistant" || !Array.isArray(value.content)) return false;
  const stopReason = value.stopReason;
  return (
    (stopReason === "stop" || stopReason === "length" || stopReason === "toolUse" || stopReason === "error" || stopReason === "aborted") &&
    isNullableString(value.errorMessage) &&
    value.content.every((block) => isTextContent(block) || isToolCallContent(block) || (isRecord(block) && block.type === "thinking" && typeof block.thinking === "string"))
  );
}

function isVisibleContent(value: unknown): boolean {
  return typeof value === "string" || (Array.isArray(value) && value.every((block) => isTextContent(block) || isImageContent(block)));
}

function isWireMessage(value: unknown): value is WireMessage {
  if (!isRecord(value) || typeof value.role !== "string") return false;
  if (value.role === "assistant") return isAssistantMessage(value);
  if (value.role === "user") return isVisibleContent(value.content);
  if (value.role === "toolResult") {
    return typeof value.toolCallId === "string" && typeof value.toolName === "string" && Array.isArray(value.content) && value.content.every((block) => isTextContent(block) || isImageContent(block)) && typeof value.isError === "boolean";
  }
  return value.role === "custom" && typeof value.customType === "string" && isVisibleContent(value.content);
}

function isToolResult(value: unknown): value is AgentToolResult {
  return isRecord(value) && Array.isArray(value.content) && value.content.every((block) => isTextContent(block) || isImageContent(block)) && typeof value.isError === "boolean";
}

function isAssistantEvent(value: unknown): value is AssistantMessageEvent {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  if (value.type === "start") return isAssistantMessage(value.partial);
  if (value.type === "text_start" || value.type === "thinking_start" || value.type === "toolcall_start") {
    return typeof value.contentIndex === "number" && isAssistantMessage(value.partial);
  }
  if (value.type === "text_delta" || value.type === "thinking_delta" || value.type === "toolcall_delta") {
    return typeof value.contentIndex === "number" && typeof value.delta === "string" && isAssistantMessage(value.partial);
  }
  if (value.type === "text_end" || value.type === "thinking_end") {
    return typeof value.contentIndex === "number" && typeof value.content === "string" && isAssistantMessage(value.partial);
  }
  if (value.type === "toolcall_end") return typeof value.contentIndex === "number" && isToolCallContent(value.toolCall) && isAssistantMessage(value.partial);
  if (value.type === "done") return (value.reason === "stop" || value.reason === "length" || value.reason === "toolUse") && isAssistantMessage(value.message);
  return value.type === "error" && (value.reason === "error" || value.reason === "aborted") && isAssistantMessage(value.error);
}

/** 严格解码 camelCase wire event；非法载荷不做宽松兼容。 */
export function decodeServerEvent(value: unknown): ServerEvent | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  let valid = false;
  switch (value.type) {
    case "agent_start": case "agent_end": case "turn_start": case "agent_settled": valid = true; break;
    case "turn_end": valid = isWireMessage(value.message) && Array.isArray(value.toolResults) && value.toolResults.every(isWireMessage); break;
    case "message_start": case "message_end": case "turn_failed": valid = isWireMessage(value.message); break;
    case "message_update": valid = isWireMessage(value.message) && isAssistantEvent(value.assistantMessageEvent); break;
    case "tool_execution_start": valid = typeof value.toolCallId === "string" && typeof value.toolName === "string" && isRecord(value.args); break;
    case "tool_execution_update": valid = typeof value.toolCallId === "string" && typeof value.toolName === "string" && isRecord(value.args) && isToolResult(value.partialResult); break;
    case "tool_execution_end": valid = typeof value.toolCallId === "string" && typeof value.toolName === "string" && isToolResult(value.result) && typeof value.isError === "boolean"; break;
    case "cancelled": valid = value.message === undefined || value.message === null || isWireMessage(value.message); break;
    case "session_agent_end": valid = typeof value.willRetry === "boolean"; break;
    case "queue_update": valid = isStringArray(value.steering) && isStringArray(value.followUp); break;
    case "compaction_started": case "compaction_start": valid = isCompactionReason(value.reason); break;
    case "compaction_completed": valid = isCompactionReason(value.reason) && typeof value.aborted === "boolean"; break;
    case "compaction_end": valid = isCompactionReason(value.reason) && typeof value.aborted === "boolean" && typeof value.willRetry === "boolean" && (value.errorMessage === undefined || isNullableString(value.errorMessage)); break;
    case "auto_retry_start": valid = typeof value.attempt === "number" && typeof value.maxAttempts === "number" && typeof value.delayMs === "number" && typeof value.errorMessage === "string"; break;
    case "auto_retry_end": valid = typeof value.success === "boolean" && typeof value.attempt === "number" && (value.finalError === undefined || isNullableString(value.finalError)); break;
    case "confirm_request": valid = typeof value.requestId === "string" && typeof value.message === "string"; break;
    case "plan_approval_request": valid = typeof value.requestId === "string" && typeof value.plan === "string"; break;
    case "notice": valid = typeof value.text === "string" && (value.role === "info" || value.role === "error" || value.role === "status"); break;
    case "server_error": case "protocol_error": valid = typeof value.message === "string"; break;
  }
  return valid ? value as ServerEvent : null;
}

export interface ChatQueueState { steering: string[]; followUp: string[] }
export type RuntimeNotice =
  | { kind: "retry"; attempt: number; maxAttempts: number; delayMs: number; errorMessage: string }
  | { kind: "compaction"; reason: CompactionReason };
export interface ChatMetrics {
  steps: number;
  llmMs: number;
  toolMs: number;
  llmStartMs: number | null;
  toolStartMs: Record<string, number>;
}
export interface ChatProtocolState {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentAssistantId: string | null;
  nextSequence: number;
  confirmRequest: { requestId: string; message: string } | null;
  planApprovalRequest: { requestId: string; plan: string } | null;
  queue: ChatQueueState;
  runtimeNotice: RuntimeNotice | null;
  metrics: ChatMetrics;
  thinkingStartMs: number | null;
  reasoningElapsedMs: number;
}

const emptyQueue = (): ChatQueueState => ({ steering: [], followUp: [] });
const emptyMetrics = (): ChatMetrics => ({ steps: 0, llmMs: 0, toolMs: 0, llmStartMs: null, toolStartMs: {} });
export const initialChatProtocolState: ChatProtocolState = {
  messages: [], isStreaming: false, currentAssistantId: null, nextSequence: 1,
  confirmRequest: null, planApprovalRequest: null, queue: emptyQueue(),
  runtimeNotice: null, metrics: emptyMetrics(), thinkingStartMs: null, reasoningElapsedMs: 0,
};

export type ChatProtocolAction =
  | { type: "server_event"; event: ServerEvent }
  | { type: "replace_history"; messages: ChatMessage[] }
  | { type: "append_user"; message: ChatMessage }
  | { type: "run_requested" | "disconnected" | "clear_confirm" | "clear_plan_approval" };

export function reduceChatProtocol(state: ChatProtocolState, action: ChatProtocolAction): ChatProtocolState {
  switch (action.type) {
    case "replace_history": return { ...state, messages: action.messages, isStreaming: false, currentAssistantId: null, confirmRequest: null, planApprovalRequest: null, queue: emptyQueue(), runtimeNotice: null, metrics: emptyMetrics(), thinkingStartMs: null, reasoningElapsedMs: 0 };
    case "append_user": return { ...state, messages: [...state.messages, action.message], isStreaming: true };
    case "run_requested": return { ...state, isStreaming: true };
    case "disconnected": return { ...finalizeStreaming(state), confirmRequest: null, planApprovalRequest: null };
    case "clear_confirm": return { ...state, confirmRequest: null };
    case "clear_plan_approval": return { ...state, planApprovalRequest: null };
    case "server_event": return reduceServerEvent(state, action.event);
  }
}

function reduceServerEvent(state: ChatProtocolState, event: ServerEvent): ChatProtocolState {
  switch (event.type) {
    case "agent_start": return { ...state, isStreaming: true };
    case "message_start":
      if (event.message.role === "assistant") return startAssistant(trackLlmStart(state), event.message);
      if (event.message.role === "user") return consumeQueuedUserMessage(state, event.message);
      return state;
    case "message_update": {
      const delta = event.assistantMessageEvent;
      if (delta.type === "error") return applyAssistantError(state, delta.error);
      if (delta.type === "thinking_start" || delta.type === "thinking_end") return trackThinking(state, delta.type === "thinking_start");
      if (delta.type !== "text_delta" && delta.type !== "thinking_delta") return state;
      const [next, id] = ensureAssistant(state);
      return updateMessage(next, id, (message) => delta.type === "text_delta"
        ? { ...message, content: message.content + delta.delta }
        : { ...message, reasoning: (message.reasoning ?? "") + delta.delta });
    }
    case "message_end": return event.message.role === "assistant" ? finalizeAssistant(trackLlmEnd(state), event.message) : state;
    case "turn_failed": return event.message.role === "assistant" ? applyAssistantError(state, event.message) : failStreaming(state, "Agent turn failed.");
    case "tool_execution_start": return updateTool(trackToolStart(state, event.toolCallId), event.toolCallId, () => ({ id: event.toolCallId, toolName: event.toolName, args: event.args, status: "running" }));
    case "tool_execution_update": return updateTool(state, event.toolCallId, (tool) => ({ ...tool, id: event.toolCallId, toolName: event.toolName, args: event.args, status: "running", result: toolResultText(event.partialResult) }));
    case "tool_execution_end": return updateTool(trackToolEnd(state, event.toolCallId), event.toolCallId, (tool) => ({ ...tool, id: event.toolCallId, toolName: event.toolName, status: event.isError ? "error" : "completed", result: toolResultText(event.result) }));
    case "confirm_request": return { ...state, confirmRequest: { requestId: event.requestId, message: event.message } };
    case "plan_approval_request": return { ...state, planApprovalRequest: { requestId: event.requestId, plan: event.plan } };
    case "queue_update": return { ...state, queue: { steering: event.steering, followUp: event.followUp } };
    case "server_error": case "protocol_error": return failStreaming(state, event.message);
    case "compaction_end": return event.errorMessage ? failStreaming(state, event.errorMessage) : { ...state, runtimeNotice: null };
    case "auto_retry_end": return !event.success && event.finalError ? failStreaming(state, event.finalError) : { ...state, runtimeNotice: null };
    case "cancelled": case "agent_settled": return finalizeStreaming(state);
    case "auto_retry_start": return { ...state, runtimeNotice: { kind: "retry", attempt: event.attempt, maxAttempts: event.maxAttempts, delayMs: event.delayMs, errorMessage: event.errorMessage } };
    case "compaction_start": case "compaction_started": return { ...state, runtimeNotice: { kind: "compaction", reason: event.reason } };
    case "compaction_completed": return { ...state, runtimeNotice: null };
    case "turn_start": return { ...state, metrics: { ...state.metrics, steps: state.metrics.steps + 1 } };
    case "agent_end": case "turn_end": case "session_agent_end": case "notice": return state;
  }
}

function consumeQueuedUserMessage(state: ChatProtocolState, message: WireMessage & { role: "user" }): ChatProtocolState {
  const content = typeof message.content === "string" ? message.content : message.content.filter(isTextContent).map((block) => block.text).join("");
  const steeringIndex = state.queue.steering.indexOf(content);
  const followUpIndex = state.queue.followUp.indexOf(content);
  if (steeringIndex === -1 && followUpIndex === -1) return state;
  return {
    ...state,
    nextSequence: state.nextSequence + 1,
    queue: {
      steering: steeringIndex === -1 ? state.queue.steering : state.queue.steering.filter((_, index) => index !== steeringIndex),
      followUp: steeringIndex !== -1 || followUpIndex === -1 ? state.queue.followUp : state.queue.followUp.filter((_, index) => index !== followUpIndex),
    },
    messages: [...state.messages, { id: `user-live-${state.nextSequence}`, role: "user", content }],
  };
}

function ensureAssistant(state: ChatProtocolState): [ChatProtocolState, string] {
  if (state.currentAssistantId && state.messages.some((message) => message.id === state.currentAssistantId)) return [state, state.currentAssistantId];
  const id = `live-${state.nextSequence}`;
  return [{ ...state, currentAssistantId: id, nextSequence: state.nextSequence + 1, isStreaming: true, thinkingStartMs: null, reasoningElapsedMs: 0, messages: [...state.messages, { id, role: "assistant", content: "", reasoning: "", tools: [], isStreaming: true }] }, id];
}

function startAssistant(state: ChatProtocolState, message: AssistantMessage): ChatProtocolState {
  const current = state.messages.find((item) => item.id === state.currentAssistantId);
  if (current?.isStreaming) return state;
  const [next, id] = ensureAssistant({ ...state, currentAssistantId: null });
  return updateMessage(next, id, (item) => ({ ...item, content: assistantText(message), reasoning: assistantReasoning(message) }));
}

function finalizeAssistant(state: ChatProtocolState, message: AssistantMessage): ChatProtocolState {
  const [next, id] = ensureAssistant(state);
  const error = message.stopReason === "error" || message.stopReason === "aborted" ? message.errorMessage ?? `Assistant ${message.stopReason}.` : undefined;
  const canonicalTools: ToolCallItem[] = message.content.filter(isToolCallContent).map((part) => ({ id: part.id, toolName: part.name, args: part.arguments, status: "running" }));
  const updated = updateMessage(next, id, (item) => ({ ...item, content: assistantText(message), reasoning: assistantReasoning(message), tools: mergeTools(item.tools ?? [], canonicalTools), error, isStreaming: false, reasoningDuration: next.reasoningElapsedMs > 0 ? next.reasoningElapsedMs : item.reasoningDuration }));
  return error ? { ...updated, isStreaming: false } : updated;
}

function applyAssistantError(state: ChatProtocolState, message: AssistantMessage): ChatProtocolState {
  return failStreaming(finalizeAssistant(state, message), message.errorMessage ?? "Assistant provider error.");
}

function failStreaming(state: ChatProtocolState, error: string): ChatProtocolState {
  const [next, id] = ensureAssistant(state);
  return { ...updateMessage(next, id, (message) => ({ ...message, error, isStreaming: false })), isStreaming: false, currentAssistantId: null, runtimeNotice: null };
}

function finalizeStreaming(state: ChatProtocolState): ChatProtocolState {
  return { ...state, messages: state.messages.map((message) => message.id === state.currentAssistantId ? { ...message, isStreaming: false } : message), isStreaming: false, currentAssistantId: null, runtimeNotice: null };
}

function updateTool(state: ChatProtocolState, id: string, change: (tool: ToolCallItem) => ToolCallItem): ChatProtocolState {
  const [next, assistantId] = ensureAssistant(state);
  return updateMessage(next, assistantId, (message) => {
    const tools = message.tools ?? [];
    const current = tools.find((tool) => tool.id === id);
    const updated = change(current ?? { id, toolName: "Tool", status: "running" });
    return { ...message, tools: current ? tools.map((tool) => tool.id === id ? updated : tool) : [...tools, updated] };
  });
}

function updateMessage(state: ChatProtocolState, id: string, change: (message: ChatMessage) => ChatMessage): ChatProtocolState {
  return { ...state, messages: state.messages.map((message) => message.id === id ? change(message) : message) };
}
function mergeTools(live: ToolCallItem[], canonical: ToolCallItem[]): ToolCallItem[] {
  const ids = new Set(canonical.map((tool) => tool.id));
  return [...canonical.map((tool) => live.find((candidate) => candidate.id === tool.id) ?? tool), ...live.filter((tool) => !ids.has(tool.id))];
}
const assistantText = (message: AssistantMessage) => message.content.filter(isTextContent).map((part) => part.text).join("");
const assistantReasoning = (message: AssistantMessage) => message.content.filter((part): part is { type: "thinking"; thinking: string } => part.type === "thinking").map((part) => part.thinking).join("");
const toolResultText = (result: AgentToolResult) => result.content.filter(isTextContent).map((part) => part.text).join("");

/** 将本地运行耗时格式化为紧凑显示，并在分钟边界正确进位。 */
export function formatRunDuration(ms: number): string {
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1)}s`;
  const totalSeconds = Math.round(tenths / 10);
  return `${Math.floor(totalSeconds / 60)}m${totalSeconds % 60}s`;
}

const trackLlmStart = (state: ChatProtocolState): ChatProtocolState => ({ ...state, metrics: { ...state.metrics, llmStartMs: Date.now() } });
function trackLlmEnd(state: ChatProtocolState): ChatProtocolState {
  const start = state.metrics.llmStartMs;
  return start === null ? state : { ...state, metrics: { ...state.metrics, llmMs: state.metrics.llmMs + Date.now() - start, llmStartMs: null } };
}
function trackToolStart(state: ChatProtocolState, id: string): ChatProtocolState {
  return { ...state, metrics: { ...state.metrics, toolStartMs: { ...state.metrics.toolStartMs, [id]: Date.now() } } };
}
function trackToolEnd(state: ChatProtocolState, id: string): ChatProtocolState {
  const start = state.metrics.toolStartMs[id];
  if (start === undefined) return state;
  const toolStartMs = { ...state.metrics.toolStartMs };
  delete toolStartMs[id];
  return { ...state, metrics: { ...state.metrics, toolMs: state.metrics.toolMs + Date.now() - start, toolStartMs } };
}
function trackThinking(state: ChatProtocolState, started: boolean): ChatProtocolState {
  if (started) return state.thinkingStartMs === null ? { ...state, thinkingStartMs: Date.now() } : state;
  return state.thinkingStartMs === null ? state : { ...state, thinkingStartMs: null, reasoningElapsedMs: state.reasoningElapsedMs + Date.now() - state.thinkingStartMs };
}

export function actionForInput(input: string): ClientAction | null {
  const text = input.trim();
  if (!text) return null;
  if (text === "/continue") return { action: "continue" };
  if (text === "/compact") return { action: "compact" };
  if (text.startsWith("/")) return { action: "command", command: text };
  return { action: "prompt", prompt: text };
}
