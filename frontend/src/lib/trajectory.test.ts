import { describe, expect, it, vi, afterEach } from "vitest";

import type { ServerEvent } from "./chatProtocol";
import {
  foldTrajectory,
  initialTrajectoryLiveState,
  reduceTrajectoryLive,
  type TrajectoryLiveState,
} from "./trajectory";
import type { ChatMessage } from "@/types/chat";

// 打点 reducer 直接读 performance.now（与 chatProtocol 的 metrics 同模式），
// 测试用 spyOn 控制时钟
afterEach(() => {
  vi.restoreAllMocks();
});

function mockClock(...times: number[]) {
  const spy = vi.spyOn(performance, "now");
  times.forEach((t) => spy.mockReturnValueOnce(t));
  return spy;
}

function apply(state: TrajectoryLiveState, event: ServerEvent) {
  return reduceTrajectoryLive(state, { type: "server_event", event });
}

const emptyAssistant = {
  role: "assistant" as const,
  content: [] as never[],
  stopReason: "stop" as const,
  errorMessage: null,
};

function assistantEnd(): ServerEvent {
  return { type: "message_end", message: { ...emptyAssistant, content: [] } };
}

describe("trajectory live reducer", () => {
  it("pairs assistant message_start/end into one closed span", () => {
    mockClock(100, 350);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    expect(state.assistantSpans).toEqual([{ startMs: 100, endMs: 350 }]);
  });

  it("closes the previous unclosed span when a retry chain starts a new one", () => {
    // 溢出重试：失败尝试没有 message_end，新 message_start 必须先收尾旧 span
    //（message_start 内两次打钟：关旧 + 开新）
    mockClock(100, 200, 300, 500, 700);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, { type: "auto_retry_start", attempt: 1, maxAttempts: 5, delayMs: 3000, errorMessage: "overflow" });
    state = apply(state, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, { type: "auto_retry_end", success: true, attempt: 1 });
    expect(state.assistantSpans).toEqual([
      { startMs: 100, endMs: 300 },
      { startMs: 500, endMs: null },
    ]);
    // retry mark 被成功关闭
    expect(state.marks[0]).toMatchObject({ kind: "retry", success: true, endMs: 700 });
  });

  it("pairs tool spans by toolCallId and records error state", () => {
    mockClock(10, 99);
    let state = apply(initialTrajectoryLiveState, {
      type: "tool_execution_start",
      toolCallId: "call-a",
      toolName: "read_file",
      args: {},
    });
    state = apply(state, {
      type: "tool_execution_end",
      toolCallId: "call-a",
      toolName: "read_file",
      result: { content: [], isError: true },
      isError: true,
    });
    expect(state.toolSpans["call-a"]).toEqual({
      startMs: 10,
      endMs: 99,
      toolName: "read_file",
      isError: true,
    });
  });

  it("closes compaction marks from either the app-level or core-level end event", () => {
    mockClock(1, 30, 60, 90);
    let state = apply(initialTrajectoryLiveState, { type: "compaction_start", reason: "manual" });
    state = apply(state, { type: "compaction_end", reason: "manual", aborted: false, willRetry: false, errorMessage: null });
    state = apply(state, { type: "compaction_started", reason: "threshold" });
    state = apply(state, { type: "compaction_completed", reason: "threshold", aborted: false });
    expect(state.marks.map((m) => [m.kind, m.kind === "compaction" ? m.reason : "", m.endMs])).toEqual([
      ["compaction", "manual", 30],
      ["compaction", "threshold", 90],
    ]);
  });

  it("finalize closes every in-flight span and mark (stream end fallback)", () => {
    // finalize 对 3 个进行中打点各打一次钟，统一落在 500
    mockClock(5, 6, 7, 500, 500, 500);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, {
      type: "tool_execution_start",
      toolCallId: "call-x",
      toolName: "agent",
      args: {},
    });
    state = apply(state, { type: "auto_retry_start", attempt: 2, maxAttempts: 5, delayMs: 1000, errorMessage: "boom" });
    state = reduceTrajectoryLive(state, { type: "finalize" });
    expect(state.assistantSpans[0].endMs).toBe(500);
    expect(state.toolSpans["call-x"].endMs).toBe(500);
    expect(state.marks[0].endMs).toBe(500);
  });

  it("closes the open span on stream-terminal events that never send message_end", () => {
    // 取消/失败终态：不收尾的话 span 要等下一条 message_start 补关，
    // 中间空闲间隔会被计入上一条消息的耗时（虚高）
    mockClock(100, 200, 300, 400);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, { type: "cancelled", message: null });
    state = apply(state, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    expect(state.assistantSpans).toEqual([
      { startMs: 100, endMs: 200 },
      { startMs: 300, endMs: 400 },
    ]);
  });

  it("reset clears all collected data (session switch)", () => {
    mockClock(5, 6);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = reduceTrajectoryLive(state, { type: "reset" });
    expect(state).toEqual(initialTrajectoryLiveState);
  });
});

// ─── 折叠器：历史（messages 投影）+ 实时打点的拼合 ───

function historyFixture(): ChatMessage[] {
  return [
    { id: "msg-0", role: "user", content: "检查架构" },
    {
      id: "msg-1",
      role: "assistant",
      content: "先看目录结构",
      tools: [{ id: "call-hist", toolName: "grep", status: "completed", result: "old hits" }],
    },
    { id: "msg-2", role: "user", content: "继续" },
    {
      id: "msg-3",
      role: "assistant",
      content: "新的结论",
      tools: [{ id: "call-live", toolName: "edit_file", status: "error", result: "conflict" }],
    },
  ];
}

describe("foldTrajectory", () => {
  it("projects message-level rows in order with no durations when no live data", () => {
    const rows = foldTrajectory(historyFixture(), initialTrajectoryLiveState);
    expect(rows.map((r) => r.kind)).toEqual([
      "user",
      "assistant",
      "tool",
      "user",
      "assistant",
      "tool",
    ]);
    // 历史段无打点：全部耗时为 null（不显示耗时条）
    expect(rows.every((r) => r.kind !== "assistant" || r.durationMs === null)).toBe(true);
    expect(rows.every((r) => r.kind !== "tool" || r.durationMs === null)).toBe(true);
    // 工具行携带状态与入参出参（详情展开数据源）
    const toolRow = rows.find((r) => r.kind === "tool" && r.id === "call-hist");
    expect(toolRow).toMatchObject({ label: "grep" });
  });

  it("tail-aligns assistant spans so history rows stay bare and live rows get durations", () => {
    // 2 条 assistant 消息、1 个实时 span：耗时只能落在最后一条（尾部对齐）
    mockClock(1000, 4000);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());

    const rows = foldTrajectory(historyFixture(), state);
    const assistantRows = rows.filter((r) => r.kind === "assistant");
    expect(assistantRows[0].durationMs).toBeNull();
    expect(assistantRows[1]).toMatchObject({ id: "assistant-msg-3", durationMs: 3000 });
  });

  it("keeps tool durations matched by toolCallId after history replacement (no duplicate rows)", () => {
    // 重连场景：messages 被 canonical history 替换（实时消息已折叠为 msg-*），
    // 打点保留——行数仍等于消息投影，工具耗时按 id 重新挂上
    mockClock(50, 150);
    let state = apply(initialTrajectoryLiveState, {
      type: "tool_execution_start",
      toolCallId: "call-live",
      toolName: "edit_file",
      args: {},
    });
    state = apply(state, {
      type: "tool_execution_end",
      toolCallId: "call-live",
      toolName: "edit_file",
      result: { content: [{ type: "text", text: "conflict" }], isError: true },
      isError: true,
    });

    const rows = foldTrajectory(historyFixture(), state);
    const toolRows = rows.filter((r) => r.kind === "tool");
    expect(toolRows).toHaveLength(2);
    expect(rows.find((r) => r.id === "call-live")).toMatchObject({ durationMs: 100 });
    expect(rows.find((r) => r.id === "call-hist")).toMatchObject({ durationMs: null });
  });

  it("inserts compaction/retry marks after their anchored assistant block", () => {
    // compaction anchor=1（第一个 span 开启后）→ 插在 msg-3 块前；
    // retry anchor=2（第二个 span 开启后、无下一个块）→ 追加到时间线末尾
    mockClock(100, 200, 300, 400, 500, 600);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, { type: "compaction_start", reason: "threshold" });
    state = apply(state, { type: "compaction_end", reason: "threshold", aborted: false, willRetry: false, errorMessage: null });
    state = apply(state, assistantEnd());
    state = apply(state, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, { type: "auto_retry_start", attempt: 1, maxAttempts: 5, delayMs: 0, errorMessage: "err" });

    const rows = foldTrajectory(historyFixture(), state);
    expect(rows.map((r) => [r.kind, r.id])).toEqual([
      ["user", "user-msg-0"],
      ["assistant", "assistant-msg-1"],
      ["tool", "call-hist"],
      ["user", "user-msg-2"],
      ["compaction", "mark-1-0"],
      ["assistant", "assistant-msg-3"],
      ["tool", "call-live"],
      ["retry", "mark-2-0"],
    ]);
    const compaction = rows.find((r) => r.kind === "compaction");
    expect(compaction).toMatchObject({ reason: "threshold", durationMs: 100 });
    const retry = rows.find((r) => r.kind === "retry");
    expect(retry).toMatchObject({ attempt: 1, success: null, durationMs: null });
  });

  it("appends tail-anchored marks when no live assistant span exists yet", () => {
    // 页面刚打开（无实时 assistant 消息）就发生压缩：anchor=0 == span 数，
    // 无可插入的 live 块 → 追加尾部，按发生序排列
    mockClock(1, 2, 3, 4);
    let state = apply(initialTrajectoryLiveState, { type: "compaction_started", reason: "overflow" });
    state = apply(state, { type: "compaction_completed", reason: "overflow", aborted: false });
    state = apply(state, { type: "auto_retry_start", attempt: 1, maxAttempts: 3, delayMs: 0, errorMessage: "x" });

    const rows = foldTrajectory(historyFixture(), state);
    expect(rows.slice(-2).map((r) => r.kind)).toEqual(["compaction", "retry"]);
  });

  it("defends against spans exceeding assistant rows after history wipe", () => {
    // replace_history([]) 后消息清空但打点未 reset 的瞬态：截断尾部 span，
    // 不越界、不产出消息行
    mockClock(10, 20, 30, 40);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    state = apply(state, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());

    const rows = foldTrajectory([], state);
    expect(rows).toEqual([]);
  });

  it("appends marks left dangling by span truncation at the tail instead of dropping them", () => {
    // 重连后历史被压缩折叠：2 个 span 只剩 1 条 assistant 消息可挂，
    // 锚点悬空的压缩 mark 追加尾部展示（"超界追加尾部"不变量）
    mockClock(10, 20, 30, 40, 50, 60);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    state = apply(state, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    state = apply(state, { type: "compaction_start", reason: "overflow" });
    state = apply(state, { type: "compaction_end", reason: "overflow", aborted: false, willRetry: false, errorMessage: null });

    const rows = foldTrajectory([{ id: "a", role: "assistant", content: "折叠摘要" }], state);
    expect(rows.map((r) => r.kind)).toEqual(["assistant", "compaction"]);
  });

  it("keeps mark row ids stable when new spans promote tail marks into the timeline", () => {
    // 压缩 anchor=1：span 1 出现前 mark 挂尾部，出现后移入块间——
    // id 必须不变，否则展开/高亮状态随流式进行丢失
    mockClock(1, 2, 3, 4, 5, 6);
    let state = apply(initialTrajectoryLiveState, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    state = apply(state, { type: "compaction_start", reason: "threshold" });
    state = apply(state, { type: "compaction_end", reason: "threshold", aborted: false, willRetry: false, errorMessage: null });
    const before = foldTrajectory(
      [{ id: "a1", role: "assistant", content: "x" }],
      state,
    ).find((r) => r.kind === "compaction");
    state = apply(state, {
      type: "message_start",
      message: { ...emptyAssistant },
    });
    state = apply(state, assistantEnd());
    const after = foldTrajectory(
      [
        { id: "a1", role: "assistant", content: "x" },
        { id: "a2", role: "assistant", content: "y" },
      ],
      state,
    ).find((r) => r.kind === "compaction");
    expect(before?.id).toBe("mark-1-0");
    expect(after?.id).toBe("mark-1-0");
  });

  it("summarizes user content to first line and tool args by preferred keys", () => {
    const rows = foldTrajectory(
      [
        { id: "u1", role: "user", content: "第一行\n第二行" },
        {
          id: "a1",
          role: "assistant",
          content: "",
          tools: [
            {
              id: "t1",
              toolName: "exec_command",
              args: { CommandLine: "pytest -q" },
              status: "completed",
            },
          ],
        },
      ],
      initialTrajectoryLiveState,
    );
    expect(rows[0]).toMatchObject({ kind: "user", label: "第一行", content: "第一行\n第二行" });
    expect(rows[2]).toMatchObject({ kind: "tool", label: "exec_command", summary: "pytest -q" });
    // 空文本 + 工具轮的 assistant 行回退为占位摘要
    expect(rows[1]).toMatchObject({ kind: "assistant", label: "工具调用" });
  });
});
