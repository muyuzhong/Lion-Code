import type { ChatMessage, ToolCallItem } from "@/types/chat";
import type { ServerEvent } from "./chatProtocol";

// ─── 轨迹数据层（P1-7 简版）───
// 数据面边界：协议事件无服务端时间戳、/api/messages 的 createdAt 恒为 null，
// 历史段只有消息序（无耗时数据）；耗时只能来自本页连接期间的实时打点
// （performance.now 相对毫秒）。消息行始终从 ChatProtocolState.messages 投影
// （单一事实源），打点只做增强（耗时 + 压缩/重试行），结构上杜绝历史与实时重复。

export interface TrajectorySpan {
  startMs: number;
  endMs: number | null; // null = 进行中
}

export interface TrajectoryToolSpan extends TrajectorySpan {
  toolName: string;
  isError: boolean;
}

interface TrajectoryMarkBase extends TrajectorySpan {
  // 打点时已开启的 assistant span 数（含进行中的）。折叠时据此插入消息流：
  // performance.now 域与消息顺序域无法互相排序，锚点是唯一的衔接依据。
  anchor: number;
}

export interface CompactionMark extends TrajectoryMarkBase {
  kind: "compaction";
  reason: string;
  aborted: boolean | null; // null = 进行中
}

export interface RetryMark extends TrajectoryMarkBase {
  kind: "retry";
  attempt: number;
  maxAttempts: number;
  errorMessage: string;
  success: boolean | null; // null = 进行中
}

export type TrajectoryMark = CompactionMark | RetryMark;

export interface TrajectoryLiveState {
  assistantSpans: TrajectorySpan[];
  toolSpans: Record<string, TrajectoryToolSpan>;
  marks: TrajectoryMark[];
}

export const initialTrajectoryLiveState: TrajectoryLiveState = {
  assistantSpans: [],
  toolSpans: {},
  marks: [],
};

export type TrajectoryAction =
  | { type: "server_event"; event: ServerEvent }
  // 流终止/断连兜底：进行中打点不关闭会永远显示"进行中"
  | { type: "finalize" }
  // 换会话清空；WS 重连（replace_history）不清——重连后消息以服务端折叠
  // 历史回归，尾部对齐仍成立，打点数据得以保留
  | { type: "reset" };

// 打点时钟与 chatProtocol 的 metrics 同模式（reducer 内直接读钟，
// 测试用 vi.spyOn(performance, "now") 控制）
function now(): number {
  return performance.now();
}

function closeSpan<T extends TrajectorySpan>(span: T): T {
  return span.endMs === null ? { ...span, endMs: now() } : span;
}

export function reduceTrajectoryLive(
  state: TrajectoryLiveState,
  action: TrajectoryAction,
): TrajectoryLiveState {
  switch (action.type) {
    case "reset":
      return initialTrajectoryLiveState;
    case "finalize":
      return {
        assistantSpans: state.assistantSpans.map(closeSpan),
        toolSpans: Object.fromEntries(
          Object.entries(state.toolSpans).map(([id, span]) => [
            id,
            closeSpan(span),
          ]),
        ),
        marks: state.marks.map(closeSpan),
      };
    case "server_event":
      return reduceTrajectoryEvent(state, action.event);
  }
}

function reduceTrajectoryEvent(
  state: TrajectoryLiveState,
  event: ServerEvent,
): TrajectoryLiveState {
  switch (event.type) {
    case "message_start":
      if (event.message.role !== "assistant") return state;
      // 溢出重试链中上一次失败尝试不会有 message_end，开新 span 前先关闭
      // 旧的（与 metrics.llmStartMs 的覆盖起点逻辑同理）
      return {
        ...state,
        assistantSpans: [
          ...state.assistantSpans.map(closeSpan),
          { startMs: now(), endMs: null },
        ],
      };
    case "message_end":
    case "turn_failed":
      if (event.message.role !== "assistant") return state;
      return closeLastAssistantSpan(state);
    // 这些流终态没有 message_end：不收尾的话 span 要等下一次 message_start
    // 才补关，中间的间隔会被错误计入上一条消息的耗时（虚高）
    case "cancelled":
    case "server_error":
    case "protocol_error":
      return closeLastAssistantSpan(state);
    case "tool_execution_start":
      return {
        ...state,
        toolSpans: {
          ...state.toolSpans,
          [event.toolCallId]: {
            startMs: now(),
            endMs: null,
            toolName: event.toolName,
            isError: false,
          },
        },
      };
    case "tool_execution_end": {
      const span = state.toolSpans[event.toolCallId];
      if (!span) return state;
      return {
        ...state,
        toolSpans: {
          ...state.toolSpans,
          [event.toolCallId]: { ...span, endMs: now(), isError: event.isError },
        },
      };
    }
    case "compaction_start":
    case "compaction_started":
      return {
        ...state,
        marks: [
          ...state.marks,
          {
            kind: "compaction" as const,
            reason: event.reason,
            aborted: null,
            startMs: now(),
            endMs: null,
            anchor: state.assistantSpans.length,
          },
        ],
      };
    case "compaction_end":
    case "compaction_completed":
      // 两层事件架构（应用级 end / 核心级 completed）任一到达都算结束
      return updateLastOpenMark(state, "compaction", (mark) => ({
        ...mark,
        ...closeSpan(mark),
        aborted: event.aborted,
      }));
    case "auto_retry_start":
      return {
        ...state,
        marks: [
          ...state.marks,
          {
            kind: "retry" as const,
            attempt: event.attempt,
            maxAttempts: event.maxAttempts,
            errorMessage: event.errorMessage,
            success: null,
            startMs: now(),
            endMs: null,
            anchor: state.assistantSpans.length,
          },
        ],
      };
    case "auto_retry_end":
      return updateLastOpenMark(state, "retry", (mark) => ({
        ...mark,
        ...closeSpan(mark),
        success: event.success,
      }));
    default:
      return state;
  }
}

function closeLastAssistantSpan(state: TrajectoryLiveState): TrajectoryLiveState {
  for (let i = state.assistantSpans.length - 1; i >= 0; i -= 1) {
    if (state.assistantSpans[i].endMs === null) {
      const assistantSpans = state.assistantSpans.slice();
      assistantSpans[i] = closeSpan(assistantSpans[i]);
      return { ...state, assistantSpans };
    }
  }
  return state;
}

function updateLastOpenMark(
  state: TrajectoryLiveState,
  kind: TrajectoryMark["kind"],
  update: (mark: TrajectoryMark) => TrajectoryMark,
): TrajectoryLiveState {
  for (let i = state.marks.length - 1; i >= 0; i -= 1) {
    const mark = state.marks[i];
    if (mark.kind === kind && mark.endMs === null) {
      const marks = state.marks.slice();
      marks[i] = update(mark);
      return { ...state, marks };
    }
  }
  return state;
}

// ─── 折叠器：消息投影 + 实时打点 → 轨迹行序列（纯函数）───

export type TrajectoryRow =
  | { id: string; kind: "user"; label: string; content: string }
  | {
      id: string;
      kind: "assistant";
      label: string;
      message: ChatMessage;
      durationMs: number | null; // null = 历史无打点或进行中
      isStreaming: boolean;
    }
  | {
      id: string;
      kind: "tool";
      label: string;
      summary: string | null;
      tool: ToolCallItem;
      durationMs: number | null;
    }
  | {
      id: string;
      kind: "compaction";
      reason: string;
      durationMs: number | null;
      aborted: boolean | null;
    }
  | {
      id: string;
      kind: "retry";
      attempt: number;
      maxAttempts: number;
      errorMessage: string;
      durationMs: number | null;
      success: boolean | null;
    };

function spanDuration(span: TrajectorySpan | undefined): number | null {
  if (!span || span.endMs === null) return null;
  return span.endMs - span.startMs;
}

export function foldTrajectory(
  messages: ChatMessage[],
  live: TrajectoryLiveState,
): TrajectoryRow[] {
  // assistant 打点尾部对齐消息流：打点覆盖的是会话尾部产生的消息。重连后
  // canonical history 已包含此前的实时消息，尾部对齐让耗时落到同一条消息上
  // （去重/衔接的关键不变量：打点数 <= 消息中的 assistant 数）。
  const assistantCount = messages.filter((m) => m.role === "assistant").length;
  let spans = live.assistantSpans;
  if (spans.length > assistantCount) {
    // 防御：消息被清空（replace_history([])）而打点未 reset 的瞬态
    spans = spans.slice(-assistantCount);
  }
  const liveOffset = assistantCount - spans.length;

  const rows: TrajectoryRow[] = [];
  let assistantIndex = 0;
  for (const message of messages) {
    if (message.role === "user") {
      rows.push({
        id: `user-${message.id}`,
        kind: "user",
        label: summarizeText(message.content),
        content: message.content,
      });
      continue;
    }
    const liveIndex = assistantIndex - liveOffset;
    // 锚点 == liveIndex 的压缩/重试打点插在其锚定 assistant 块之前；
    // 历史块（liveIndex < 0）无匹配——页面打开前的事件本就无打点。
    rows.push(...markRows(live.marks, (mark) => mark.anchor === liveIndex));
    const span =
      liveIndex >= 0 && liveIndex < spans.length ? spans[liveIndex] : undefined;
    rows.push({
      id: `assistant-${message.id}`,
      kind: "assistant",
      label: summarizeText(
        message.content ||
          message.reasoning ||
          (message.tools?.length ? "工具调用" : "助手消息"),
      ),
      message,
      durationMs: spanDuration(span),
      isStreaming: !!message.isStreaming,
    });
    for (const tool of message.tools ?? []) {
      rows.push({
        id: tool.id,
        kind: "tool",
        label: tool.toolName,
        summary: summarizeToolArgs(tool.args),
        tool,
        durationMs: spanDuration(live.toolSpans[tool.id]),
      });
    }
    assistantIndex += 1;
  }
  // 尾部追加：锚点 ≥ 当前 span 数（事件发生在最后一个 live 块之后，含历史
  // 折叠截尾后锚点悬空的 mark），按发生序追加，不丢弃
  rows.push(...markRows(live.marks, (mark) => mark.anchor >= spans.length));
  return rows;
}

// id 用「锚点 + 同锚点组内序」：mark 只追加不移除且锚点单调不降，该 id 在
// span 增长导致 mark 从尾部组移入块间组时保持不变（expanded/高亮不丢）
function markRows(
  marks: TrajectoryMark[],
  match: (mark: TrajectoryMark) => boolean,
): TrajectoryRow[] {
  const rows: TrajectoryRow[] = [];
  let currentAnchor = -1;
  let indexInAnchor = -1;
  for (const mark of marks) {
    if (mark.anchor !== currentAnchor) {
      currentAnchor = mark.anchor;
      indexInAnchor = 0;
    } else {
      indexInAnchor += 1;
    }
    if (!match(mark)) continue;
    rows.push(markToRow(mark, `mark-${mark.anchor}-${indexInAnchor}`));
  }
  return rows;
}

function markToRow(mark: TrajectoryMark, id: string): TrajectoryRow {
  return mark.kind === "compaction"
    ? {
        id,
        kind: "compaction" as const,
        reason: mark.reason,
        durationMs: spanDuration(mark),
        aborted: mark.aborted,
      }
    : {
        id,
        kind: "retry" as const,
        attempt: mark.attempt,
        maxAttempts: mark.maxAttempts,
        errorMessage: mark.errorMessage,
        durationMs: spanDuration(mark),
        success: mark.success,
      };
}

// 参数摘要：常见键名优先（命令/路径/查询/任务描述），只取字符串值，
// 不按字段形状臆测工具类型（契约见 .trellis/spec/frontend/toolview-display-contract.md）
const PREFERRED_ARG_KEYS = [
  "command",
  "CommandLine",
  "cmd",
  "path",
  "TargetFile",
  "AbsolutePath",
  "file_path",
  "query",
  "Query",
  "pattern",
  "Pattern",
  "description",
];

function summarizeToolArgs(args: ToolCallItem["args"]): string | null {
  if (!args) return null;
  if (typeof args === "string") return summarizeText(args);
  for (const key of PREFERRED_ARG_KEYS) {
    const value = args[key];
    if (typeof value === "string" && value) return summarizeText(value);
  }
  return null;
}

function summarizeText(text: string): string {
  const firstLine = text.split("\n", 1)[0].trim();
  return firstLine.length > 48 ? `${firstLine.slice(0, 48)}…` : firstLine;
}
