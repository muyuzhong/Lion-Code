import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ChevronRight,
  RefreshCw,
  Sparkles,
  User,
  Wrench,
} from "lucide-react";
import type { ChatMessage } from "@/types/chat";
import { formatRunDuration } from "@/lib/chatProtocol";
import {
  foldTrajectory,
  type TrajectoryLiveState,
  type TrajectoryRow,
} from "@/lib/trajectory";
import { ToolResultView } from "./ToolResultView";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

interface TrajectoryPanelProps {
  open: boolean;
  onClose: () => void;
  messages: ChatMessage[];
  live: TrajectoryLiveState;
  // 工具卡片"检查"入口的定位目标：对象引用语义——每次点击新建对象，
  // 重复指向同一行也能重新触发定位 effect（与 App 的 skillPrompt 同模式）
  focusTarget: { id: string } | null;
}

// 面板关闭态的 rows 占位：保持引用稳定，避免关闭期间 effect 依赖抖动
const CLOSED_ROWS: TrajectoryRow[] = [];

// 行类型级图标/配色（不按工具种类细分，简版边界；工具种类视觉归聊天卡片）
const KIND_ICON: Record<TrajectoryRow["kind"], React.ElementType> = {
  user: User,
  assistant: Sparkles,
  tool: Wrench,
  compaction: Archive,
  retry: RefreshCw,
};

const COMPACTION_REASON_LABEL: Record<string, string> = {
  manual: "手动",
  threshold: "阈值",
  overflow: "溢出",
};

interface RowVisual {
  iconClass: string;
  barClass: string;
  running: boolean;
  statusText: string | null;
}

function rowVisual(row: TrajectoryRow): RowVisual {
  switch (row.kind) {
    case "user":
      return { iconClass: "text-zinc-500", barClass: "bg-zinc-400", running: false, statusText: null };
    case "assistant":
      return {
        iconClass: row.message.error ? "text-rose-500" : "text-blue-500",
        barClass: row.message.error ? "bg-rose-500" : "bg-blue-400",
        running: row.isStreaming,
        statusText: row.isStreaming ? "生成中" : row.message.error ? "失败" : null,
      };
    case "tool":
      return {
        iconClass:
          row.tool.status === "error"
            ? "text-rose-500"
            : row.tool.status === "running"
              ? "text-amber-500"
              : "text-emerald-500",
        barClass:
          row.tool.status === "error"
            ? "bg-rose-500"
            : row.tool.status === "running"
              ? "bg-amber-400"
              : "bg-emerald-500",
        running: row.tool.status === "running",
        statusText:
          row.tool.status === "running"
            ? "执行中"
            : row.tool.status === "error"
              ? "失败"
              : null,
      };
    case "compaction":
      return {
        iconClass: "text-violet-500",
        barClass: "bg-violet-400",
        running: row.aborted === null,
        statusText: row.aborted === null ? "压缩中" : row.aborted ? "已中止" : null,
      };
    case "retry":
      return {
        iconClass: row.success === false ? "text-rose-500" : "text-amber-500",
        barClass: row.success === false ? "bg-rose-500" : "bg-amber-400",
        running: row.success === null,
        statusText: row.success === null ? "重试中" : row.success ? null : "重试失败",
      };
  }
}

// 耗时条：宽度相对面板内最大行耗时的比例（设计 P1-7 的"相对行宽比例"）
function DurationBar({
  durationMs,
  maxMs,
  barClass,
  running,
}: {
  durationMs: number | null;
  maxMs: number;
  barClass: string;
  running: boolean;
}) {
  const pct =
    durationMs !== null && maxMs > 0
      ? Math.max(2, Math.round((durationMs / maxMs) * 100))
      : 0;
  return (
    <div className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
      {durationMs !== null ? (
        <div className={cn("h-full rounded-full", barClass)} style={{ width: `${pct}%` }} />
      ) : (
        running && <div className={cn("h-full w-1/3 animate-pulse rounded-full", barClass)} />
      )}
    </div>
  );
}

function DetailPre({ text }: { text: string }) {
  return (
    <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-2.5 font-mono text-[11px] leading-relaxed text-zinc-700 dark:text-zinc-300">
      {text}
    </pre>
  );
}

function RowDetail({ row }: { row: TrajectoryRow }) {
  switch (row.kind) {
    case "user":
      return <DetailPre text={row.content} />;
    case "assistant":
      return (
        <div className="space-y-2">
          {row.message.reasoning && (
            <div>
              <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                思考过程 (Reasoning)
              </div>
              <DetailPre text={row.message.reasoning} />
            </div>
          )}
          {row.message.content && (
            <div>
              <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                回复内容 (Content)
              </div>
              <DetailPre text={row.message.content} />
            </div>
          )}
          {row.message.error && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-[11px] text-rose-700 dark:text-rose-300">
              {row.message.error}
            </div>
          )}
        </div>
      );
    case "tool":
      // 入参出参复用聊天卡片同款折叠渲染（PR④ ToolResultView：diff/ANSI/Markdown/纯文本）
      return (
        <div className="space-y-2">
          {row.tool.args && (
            <div>
              <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                输入参数 (Parameters)
              </div>
              <DetailPre
                text={
                  typeof row.tool.args === "string"
                    ? row.tool.args
                    : JSON.stringify(row.tool.args, null, 2)
                }
              />
            </div>
          )}
          {row.tool.result && (
            <div>
              <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                执行输出 (Output)
              </div>
              <ToolResultView tool={row.tool} />
            </div>
          )}
        </div>
      );
    case "compaction":
      return (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/60 p-2.5 text-[11px] text-zinc-600 dark:text-zinc-300">
          上下文压缩（触发：{COMPACTION_REASON_LABEL[row.reason] ?? row.reason}）。
          压缩后重连拉取的历史以服务端折叠摘要为准，本页实时期间的消息行保持原样。
        </div>
      );
    case "retry":
      return <DetailPre text={row.errorMessage} />;
  }
}

function rowLabel(row: TrajectoryRow): string {
  switch (row.kind) {
    case "compaction":
      return `压缩上下文（${COMPACTION_REASON_LABEL[row.reason] ?? row.reason}）`;
    case "retry":
      return `自动重试 ${row.attempt}/${row.maxAttempts}`;
    default:
      return row.label;
  }
}

export function TrajectoryPanel({
  open,
  onClose,
  messages,
  live,
  focusTarget,
}: TrajectoryPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // ref 而非 state：滚动位置判断每帧变化，不值得触发重渲染
  const atBottomRef = useRef(true);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [highlightId, setHighlightId] = useState<string | null>(null);

  // 关闭时跳过折叠：流式 delta 高频刷新 messages，关闭态全量重折纯属浪费；
  // 打开瞬间重折一次即得最新时间线
  const rows = useMemo(
    () => (open ? foldTrajectory(messages, live) : CLOSED_ROWS),
    [open, messages, live],
  );
  const maxDurationMs = useMemo(
    () =>
      rows.reduce(
        (max, row) =>
          "durationMs" in row && row.durationMs !== null
            ? Math.max(max, row.durationMs)
            : max,
        0,
      ),
    [rows],
  );

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  // Sheet 关闭即卸载滚动容器：重开时滚动位置已丢失，统一回到尾部，
  // 否则残留的 atBottom=false 会让重开后的流式停尾失效
  useEffect(() => {
    if (open) atBottomRef.current = true;
  }, [open]);

  // R5 停尾：仅当用户已停在底部时跟随新事件滚动，上滚不抢滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [rows]);

  // R4 定位：滚动到目标行并短暂高亮
  useEffect(() => {
    if (!open || !focusTarget) return;
    const el = scrollRef.current?.querySelector(
      `[data-row-id="${CSS.escape(focusTarget.id)}"]`,
    );
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    setHighlightId(focusTarget.id);
    const timer = window.setTimeout(() => setHighlightId(null), 2000);
    return () => window.clearTimeout(timer);
  }, [open, focusTarget]);

  const toggleRow = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent
        side="right"
        className="w-full gap-0 p-0 sm:max-w-md"
      >
        <SheetHeader className="border-b border-zinc-200 dark:border-zinc-800/80">
          <SheetTitle className="text-sm">执行轨迹</SheetTitle>
          <SheetDescription className="text-xs">
            消息级时间线：历史与实时衔接；耗时来自本页连接期间的本地打点，历史消息无耗时数据。
          </SheetDescription>
        </SheetHeader>

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex-1 space-y-1 overflow-y-auto p-3"
        >
          {rows.length === 0 && (
            <div className="py-16 text-center text-xs text-zinc-400 dark:text-zinc-500 select-none">
              暂无轨迹数据
            </div>
          )}
          {rows.map((row) => {
            const Icon = KIND_ICON[row.kind];
            const visual = rowVisual(row);
            const durationMs = "durationMs" in row ? row.durationMs : null;
            const expanded = expandedIds.has(row.id);
            return (
              <div
                key={row.id}
                data-row-id={row.id}
                className={cn(
                  "overflow-hidden rounded-lg border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 text-xs shadow-2xs transition",
                  highlightId === row.id && "ring-2 ring-blue-500/60",
                )}
              >
                <button
                  type="button"
                  onClick={() => toggleRow(row.id)}
                  className="flex w-full cursor-pointer items-center gap-2 px-2.5 py-1.5 text-left select-none hover:bg-zinc-50 dark:hover:bg-zinc-800/60 transition"
                >
                  <Icon className={cn("size-3.5 shrink-0", visual.iconClass, visual.running && "animate-pulse")} />
                  <span className="shrink-0 font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                    {rowLabel(row)}
                  </span>
                  {row.kind === "tool" && row.summary && (
                    <span className="min-w-0 truncate rounded-md bg-zinc-100 dark:bg-zinc-800/80 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 dark:text-zinc-300">
                      {row.summary}
                    </span>
                  )}
                  {visual.statusText && (
                    <span className="shrink-0 text-[10px] text-zinc-400 dark:text-zinc-500">
                      {visual.statusText}
                    </span>
                  )}
                  <span className="min-w-0 flex-1" />
                  <DurationBar
                    durationMs={durationMs}
                    maxMs={maxDurationMs}
                    barClass={visual.barClass}
                    running={visual.running}
                  />
                  <span className="w-12 shrink-0 text-right font-mono text-[10px] text-zinc-500 dark:text-zinc-400">
                    {durationMs !== null
                      ? formatRunDuration(durationMs)
                      : visual.running
                        ? "…"
                        : ""}
                  </span>
                  <ChevronRight
                    className={cn(
                      "size-3 shrink-0 text-zinc-400 transition-transform",
                      expanded && "rotate-90",
                    )}
                  />
                </button>
                {expanded && (
                  <div className="border-t border-zinc-200 dark:border-zinc-800/80 bg-zinc-50/60 dark:bg-zinc-950/60 p-2.5">
                    <RowDetail row={row} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </SheetContent>
    </Sheet>
  );
}
