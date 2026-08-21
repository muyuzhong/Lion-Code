import React, { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Terminal,
  FileCode,
  Search,
  Wrench,
  CheckCircle2,
  XCircle,
  Loader2,
  Copy,
  Check,
  Eye,
} from "lucide-react";
import { ToolCallItem } from "@/types/chat";

interface ToolViewProps {
  tool: ToolCallItem;
}

function getToolConfig(name: string) {
  const lower = name.toLowerCase();
  if (lower.includes("command") || lower.includes("bash") || lower.includes("shell") || lower.includes("exec")) {
    return {
      icon: Terminal,
      color: "text-amber-600 dark:text-amber-400",
      bg: "bg-amber-500/10",
      border: "border-amber-500/30",
      label: "终端执行",
    };
  }
  if (lower.includes("write") || lower.includes("create")) {
    return {
      icon: FileCode,
      color: "text-emerald-600 dark:text-emerald-400",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/30",
      label: "创建/写入文件",
    };
  }
  if (lower.includes("replace") || lower.includes("edit")) {
    return {
      icon: FileCode,
      color: "text-blue-600 dark:text-blue-400",
      bg: "bg-blue-500/10",
      border: "border-blue-500/30",
      label: "修改代码",
    };
  }
  if (lower.includes("view") || lower.includes("read")) {
    return {
      icon: Eye,
      color: "text-purple-600 dark:text-purple-400",
      bg: "bg-purple-500/10",
      border: "border-purple-500/30",
      label: "查看文件",
    };
  }
  if (lower.includes("grep") || lower.includes("search") || lower.includes("find")) {
    return {
      icon: Search,
      color: "text-cyan-600 dark:text-cyan-400",
      bg: "bg-cyan-500/10",
      border: "border-cyan-500/30",
      label: "代码检索",
    };
  }
  return {
    icon: Wrench,
    color: "text-zinc-600 dark:text-zinc-400",
    bg: "bg-zinc-500/10",
    border: "border-zinc-500/30",
    label: "工具调用",
  };
}

export function ToolView({ tool }: ToolViewProps) {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const config = getToolConfig(tool.toolName);
  const Icon = config.icon;

  const handleCopyResult = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (tool.result) {
      navigator.clipboard.writeText(tool.result);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // 提取代表性的参数摘要
  const getParamSummary = () => {
    if (!tool.args) return null;
    if (typeof tool.args === "string") return tool.args;
    if (tool.args.CommandLine) return tool.args.CommandLine;
    if (tool.args.TargetFile) return tool.args.TargetFile.split(/[/\\]/).pop();
    if (tool.args.AbsolutePath) return tool.args.AbsolutePath.split(/[/\\]/).pop();
    if (tool.args.Query) return `"${tool.args.Query}"`;
    if (tool.args.Pattern) return `Pattern: ${tool.args.Pattern}`;
    return null;
  };

  const paramSummary = getParamSummary();

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 text-xs shadow-2xs transition-all">
      {/* 头部摘要栏 */}
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex cursor-pointer items-center justify-between px-3.5 py-2.5 select-none hover:bg-zinc-50 dark:hover:bg-zinc-800/60 transition"
      >
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          <div className={`flex size-6 shrink-0 items-center justify-center rounded-lg ${config.bg} ${config.color}`}>
            <Icon className="size-3.5" />
          </div>

          <div className="flex items-center gap-2 truncate min-w-0 font-mono">
            <span className="font-semibold text-zinc-900 dark:text-zinc-100">{tool.toolName}</span>
            {paramSummary && (
              <span className="truncate rounded-md bg-zinc-100 dark:bg-zinc-800/80 px-2 py-0.5 text-[11px] text-zinc-600 dark:text-zinc-300 max-w-[200px] sm:max-w-[360px]">
                {paramSummary}
              </span>
            )}
          </div>
        </div>

        {/* 状态徽标 */}
        <div className="flex items-center gap-3 shrink-0 ml-2">
          {tool.status === "running" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400 border border-amber-500/20 animate-pulse font-sans">
              <Loader2 className="size-3 animate-spin" /> 执行中
            </span>
          )}
          {tool.status === "completed" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-sans">
              <CheckCircle2 className="size-3" /> 完成
            </span>
          )}
          {tool.status === "error" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-[10px] font-medium text-rose-600 dark:text-rose-400 border border-rose-500/20 font-sans">
              <XCircle className="size-3" /> 失败
            </span>
          )}

          <div className="text-zinc-400">
            {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </div>
        </div>
      </div>

      {/* 展开详细信息（入参与输出） */}
      {isOpen && (
        <div className="border-t border-zinc-200 dark:border-zinc-800/80 bg-zinc-50/60 dark:bg-zinc-950/60 p-3 font-mono text-[11px] space-y-3">
          {/* 参数区域 */}
          {tool.args && (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-1">
                输入参数 (Parameters)
              </div>
              <pre className="overflow-x-auto rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 p-2.5 text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap leading-relaxed">
                {typeof tool.args === "string" ? tool.args : JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          )}

          {/* 执行输出结果 */}
          {tool.result && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                  执行输出 (Output)
                </span>
                <button
                  type="button"
                  onClick={handleCopyResult}
                  className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition"
                >
                  {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
                  <span>{copied ? "已复制输出" : "复制输出"}</span>
                </button>
              </div>
              <pre
                className={`max-h-64 overflow-y-auto rounded-lg bg-zinc-950 p-2.5 whitespace-pre-wrap border border-zinc-800 font-mono text-[11px] leading-relaxed select-text ${
                  tool.status === "error" ? "text-rose-400" : "text-zinc-300"
                }`}
              >
                {tool.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
