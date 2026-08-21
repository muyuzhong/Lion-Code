import React, { useState } from "react";
import {
  TerminalIcon,
  BrainIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronUpIcon,
  ShieldCheckIcon,
  DownloadIcon,
  ArrowUpIcon,
  PlusIcon,
  SlidersHorizontalIcon,
  ArrowDownIcon,
  Settings2Icon,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface TraceStep {
  id: string;
  type: "bash" | "think" | "text" | "task_summary";
  summary?: string;
  detail?: string;
  content?: string;
  completedTasks?: number;
}

const SAMPLE_TRACES: TraceStep[] = [
  {
    id: "step-1",
    type: "bash",
    summary: "Stage production move and consumer changes",
    detail: "git add lion_code/application/ lion_code/core/ lion_code/server/",
  },
  {
    id: "step-2",
    type: "think",
    summary: "Wait, 'agent_runtime.py -> runtime/agent.py' isn't shown in the R list. Let me check — I need to add the d...",
    detail: "Analyzing git status output to ensure atomic refactoring boundaries are maintained.",
  },
  {
    id: "step-3",
    type: "bash",
    summary: "Check agent_runtime move status",
    detail: "git status --porcelain",
  },
  {
    id: "step-4",
    type: "text",
    content: "The `agent_runtime.py` deletion isn't staged yet (git needs the old path staged to detect the rename).\nLet me stage all remaining changes for this commit group.",
  },
  {
    id: "step-5",
    type: "bash",
    summary: "Stage agent_runtime.py deletion to detect rename",
    detail: "git rm --cached lion_code/agent_runtime.py",
  },
  {
    id: "step-6",
    type: "text",
    content: "Rename detected. Now commit the moved modules + production import updates:",
  },
  {
    id: "step-7",
    type: "bash",
    summary: "Commit module move and production import updates",
    detail: "git commit -m 'refactor(core): migrate agent runtime to application layer'",
  },
  {
    id: "step-8",
    type: "text",
    content: "Now commit the architecture rules + test updates (boundaries, pyproject, architecture tests, and test imports):",
  },
  {
    id: "step-9",
    type: "bash",
    summary: "Commit architecture rules and test updates",
    detail: "git add tests/ test_boundaries.py && git commit -m 'test: update architecture test suite'",
  },
  {
    id: "step-10",
    type: "text",
    content: "Now commit the docs + corpus updates (spec docs, README, OWNERSHIP, benchmark corpus):",
  },
  {
    id: "step-11",
    type: "bash",
    summary: "Commit docs and corpus updates",
    detail: "git commit -m 'docs: update architecture spec and ownership docs'",
  },
  {
    id: "step-12",
    type: "think",
    summary: "Now let me verify the working tree is clean, re-run the tests one final time on the committed state, and che...",
    detail: "Verification plan: pytest tests/ -k 'not slow' to ensure green baseline.",
  },
  {
    id: "step-13",
    type: "task_summary",
    completedTasks: 9,
  },
];

export function Thread() {
  const [activeTab, setActiveTab] = useState<"chat" | "trace">("chat");
  const [permissionMode, setPermissionMode] = useState<string>("标准模式");
  const [modelName, setModelName] = useState<string>("DeepSeek V4 Flash Max");
  const [workspaceMode, setWorkspaceMode] = useState<string>("Workspace Write");
  const [inputValue, setInputValue] = useState<string>("");
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});

  const toggleExpand = (id: string) => {
    setExpandedSteps((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground select-text">
      {/* ─── 顶部 Header ────────────────────────────────────────── */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-6 bg-background">
        <div className="flex items-center gap-4 min-w-0">
          {/* 会话标题与模式徽标 */}
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="font-semibold text-[14px] truncate text-foreground">
              你现在要继续重构仓库: https:
            </span>
            <button
              onClick={() => {
                setPermissionMode((prev) => (prev === "标准模式" ? "Plan 模式" : prev === "Plan 模式" ? "YOLO 模式" : "标准模式"));
              }}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground bg-muted/60 hover:bg-muted px-2 py-0.5 rounded-md border transition-colors cursor-pointer"
            >
              <ShieldCheckIcon className="size-3.5 text-blue-500" />
              <span>{permissionMode}</span>
              <ChevronDownIcon className="size-3" />
            </button>
          </div>

          {/* 对话 / 轨迹 切换 Tab */}
          <div className="flex items-center gap-3 text-xs font-medium ml-4">
            <button
              onClick={() => setActiveTab("chat")}
              className={cn(
                "pb-1 transition-colors cursor-pointer",
                activeTab === "chat"
                  ? "text-primary border-b-2 border-primary font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              对话
            </button>
            <button
              onClick={() => setActiveTab("trace")}
              className={cn(
                "pb-1 transition-colors cursor-pointer",
                activeTab === "trace"
                  ? "text-primary border-b-2 border-primary font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              轨迹
            </button>
          </div>
        </div>

        {/* 右侧 Session log 操作 */}
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-lg border bg-card hover:bg-muted transition-colors cursor-pointer">
            <span>Session log</span>
            <DownloadIcon className="size-3.5" />
          </button>
        </div>
      </header>

      {/* ─── 消息流视口 ────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-6 scroll-smooth relative">
        <div className="mx-auto max-w-3xl space-y-3.5">
          {SAMPLE_TRACES.map((step) => {
            if (step.type === "bash") {
              const isExpanded = !!expandedSteps[step.id];
              return (
                <div key={step.id} className="text-[13px]">
                  <button
                    onClick={() => toggleExpand(step.id)}
                    className="w-full flex items-center gap-2 text-left text-muted-foreground hover:text-foreground py-1 px-1.5 rounded hover:bg-muted/40 transition-colors group cursor-pointer"
                  >
                    <TerminalIcon className="size-4 text-muted-foreground/80 shrink-0" />
                    <span className="font-mono text-xs font-medium text-foreground/80">Bash</span>
                    <span className="text-muted-foreground/60">·</span>
                    <span className="text-muted-foreground truncate">{step.summary}</span>
                  </button>
                  {isExpanded && step.detail && (
                    <pre className="mt-1 ml-6 p-2 rounded bg-muted/60 text-xs font-mono text-muted-foreground overflow-x-auto border">
                      {step.detail}
                    </pre>
                  )}
                </div>
              );
            }

            if (step.type === "think") {
              const isExpanded = !!expandedSteps[step.id];
              return (
                <div key={step.id} className="text-[13px]">
                  <button
                    onClick={() => toggleExpand(step.id)}
                    className="w-full flex items-center gap-2 text-left text-muted-foreground hover:text-foreground py-1 px-1.5 rounded hover:bg-muted/40 transition-colors group cursor-pointer"
                  >
                    <BrainIcon className="size-4 text-muted-foreground/80 shrink-0" />
                    <span className="text-xs font-medium text-foreground/80">Think</span>
                    <span className="text-muted-foreground/60">·</span>
                    <span className="text-muted-foreground/90 truncate">{step.summary}</span>
                  </button>
                  {isExpanded && step.detail && (
                    <div className="mt-1 ml-6 p-2 rounded bg-muted/50 text-xs text-muted-foreground border leading-relaxed">
                      {step.detail}
                    </div>
                  )}
                </div>
              );
            }

            if (step.type === "text") {
              return (
                <div key={step.id} className="text-[13.5px] leading-relaxed text-foreground py-1">
                  <p className="whitespace-pre-wrap">{step.content}</p>
                </div>
              );
            }

            if (step.type === "task_summary") {
              return (
                <div key={step.id} className="pt-2">
                  <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border bg-muted/40 text-xs text-foreground font-medium">
                    <CheckCircle2Icon className="size-3.5 text-blue-500" />
                    <span>任务 {step.completedTasks} 已完成</span>
                    <ChevronUpIcon className="size-3 text-muted-foreground ml-1" />
                  </div>
                </div>
              );
            }

            return null;
          })}
        </div>

        {/* 浮动悬浮球：回到最新 */}
        <div className="sticky bottom-4 flex justify-end max-w-3xl mx-auto pointer-events-none pr-2">
          <button
            className="pointer-events-auto size-8 rounded-full border bg-card text-muted-foreground hover:text-foreground shadow-sm flex items-center justify-center hover:bg-muted transition-colors cursor-pointer"
            title="滚动到底部"
          >
            <ArrowDownIcon className="size-4" />
          </button>
        </div>
      </div>

      {/* ─── 底部输入框与控制栏 ────────────────────────────────────── */}
      <footer className="border-t bg-background px-6 pt-3 pb-2 shrink-0">
        <div className="mx-auto max-w-3xl space-y-2">
          {/* 输入框主卡片 */}
          <div className="border border-border/90 rounded-2xl bg-card p-3 shadow-xs focus-within:border-ring focus-within:ring-1 focus-within:ring-ring/20 transition-all">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="给智能体发消息"
              rows={1}
              className="w-full resize-none bg-transparent px-1 py-1 text-[13.5px] placeholder:text-muted-foreground/60 outline-none leading-relaxed min-h-[28px]"
            />

            {/* 底部功能条 */}
            <div className="flex items-center justify-between pt-2 border-t border-border/40 mt-1">
              {/* 左侧：+ 附件 和 Workspace Write 模式选择 */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="size-6 flex items-center justify-center rounded-full text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
                  title="添加附件/引用"
                >
                  <PlusIcon className="size-4" />
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setWorkspaceMode((prev) => (prev === "Workspace Write" ? "Workspace ReadOnly" : "Workspace Write"));
                  }}
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded-md hover:bg-muted transition-colors cursor-pointer"
                >
                  <Settings2Icon className="size-3.5 text-muted-foreground" />
                  <span className="font-medium text-foreground/80">{workspaceMode}</span>
                  <ChevronDownIcon className="size-3 text-muted-foreground" />
                </button>
              </div>

              {/* 右侧：模型选择器、状态圆圈、发送按钮 */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setModelName((prev) => (prev.includes("DeepSeek") ? "Claude 3.5 Sonnet" : "DeepSeek V4 Flash Max"));
                  }}
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded hover:bg-muted transition-colors cursor-pointer"
                >
                  <span className="font-medium text-foreground/80">{modelName}</span>
                  <ChevronDownIcon className="size-3 text-muted-foreground" />
                </button>

                {/* 状态圆圈指示器 */}
                <div className="size-2 rounded-full border border-muted-foreground/40 bg-muted-foreground/10" title="空闲" />

                {/* 向上发送按钮 */}
                <button
                  type="button"
                  className="size-7 rounded-full bg-blue-500 text-white flex items-center justify-center hover:bg-blue-600 transition-colors shadow-2xs cursor-pointer"
                  title="发送"
                >
                  <ArrowUpIcon className="size-4 stroke-[2.5]" />
                </button>
              </div>
            </div>
          </div>

          {/* 底部状态统计指标条 */}
          <div className="text-center text-[11px] text-muted-foreground/70 tracking-tight select-none py-1">
            <span>2 轮 · 270 步</span>
            <span className="mx-2 text-border">|</span>
            <span>LLM 97m51s · 工具调用 10m19s</span>
            <span className="mx-2 text-border">|</span>
            <span>首 token 平均 9.2s · 56 tok/s</span>
            <span className="mx-2 text-border">|</span>
            <span>缓存命中 99%</span>
            <span className="mx-2 text-border">|</span>
            <span>输入 64.5M tok · 输出 128.4k tok</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
