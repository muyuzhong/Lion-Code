import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal, FileCode, Search, Wrench, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { ToolCallItem } from "@/types/chat";

interface ToolViewProps {
  tool: ToolCallItem;
}

function getToolIcon(name: string) {
  const lower = name.toLowerCase();
  if (lower.includes("command") || lower.includes("bash") || lower.includes("shell") || lower.includes("exec")) {
    return Terminal;
  }
  if (lower.includes("file") || lower.includes("write") || lower.includes("edit") || lower.includes("replace")) {
    return FileCode;
  }
  if (lower.includes("grep") || lower.includes("search") || lower.includes("find")) {
    return Search;
  }
  return Wrench;
}

export function ToolView({ tool }: ToolViewProps) {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const Icon = getToolIcon(tool.toolName);

  return (
    <div className="mb-2 overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs shadow-2xs">
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex cursor-pointer items-center justify-between px-3.5 py-2 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
      >
        <div className="flex items-center gap-2 font-mono">
          <div className="flex size-5 items-center justify-center rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
            <Icon className="size-3.5" />
          </div>
          <span className="font-semibold text-zinc-900 dark:text-zinc-100">{tool.toolName}</span>
          {tool.args?.CommandLine && (
            <span className="max-w-[240px] sm:max-w-[320px] truncate text-[11px] text-zinc-500 dark:text-zinc-400">
              {tool.args.CommandLine}
            </span>
          )}
          {tool.args?.TargetFile && (
            <span className="max-w-[240px] sm:max-w-[320px] truncate text-[11px] text-zinc-500 dark:text-zinc-400">
              {tool.args.TargetFile.split(/[/\\]/).pop()}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {tool.status === "running" && (
            <span className="flex items-center gap-1 text-[11px] text-amber-500 font-medium font-sans">
              <Loader2 className="size-3 animate-spin" /> 执行中
            </span>
          )}
          {tool.status === "completed" && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400 font-medium font-sans">
              <CheckCircle2 className="size-3" /> 完成
            </span>
          )}
          {tool.status === "error" && (
            <span className="flex items-center gap-1 text-[11px] text-rose-500 font-medium font-sans">
              <XCircle className="size-3" /> 失败
            </span>
          )}
          {isOpen ? (
            <ChevronDown className="size-3.5 text-zinc-400" />
          ) : (
            <ChevronRight className="size-3.5 text-zinc-400" />
          )}
        </div>
      </div>

      {isOpen && (
        <div className="border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-950/60 p-3 font-mono text-[11px] space-y-2.5">
          {tool.args && (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-1">
                参数 (Parameters)
              </div>
              <pre className="overflow-x-auto rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 p-2.5 text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap">
                {typeof tool.args === "string" ? tool.args : JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          )}

          {tool.result && (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-1">
                输出结果 (Output)
              </div>
              <pre
                className={`max-h-60 overflow-y-auto rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 p-2.5 whitespace-pre-wrap ${
                  tool.status === "error" ? "text-rose-500" : "text-zinc-800 dark:text-zinc-200"
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
