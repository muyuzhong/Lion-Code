import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal, FileCode, Search, Wrench, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { ToolCallItem } from "@/types/chat";
import { cn } from "@/lib/utils";

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
    <div className="mb-2.5 overflow-hidden rounded-lg border border-border/70 bg-card/60 text-xs shadow-xs">
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex cursor-pointer items-center justify-between px-3 py-2 transition hover:bg-muted/40"
      >
        <div className="flex items-center gap-2 font-mono">
          <div className="flex size-5 items-center justify-center rounded bg-muted text-muted-foreground">
            <Icon className="size-3.5" />
          </div>
          <span className="font-semibold text-foreground">{tool.toolName}</span>
          {tool.args?.CommandLine && (
            <span className="max-w-[280px] truncate text-[11px] text-muted-foreground">
              {tool.args.CommandLine}
            </span>
          )}
          {tool.args?.TargetFile && (
            <span className="max-w-[280px] truncate text-[11px] text-muted-foreground">
              {tool.args.TargetFile.split(/[/\\]/).pop()}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {tool.status === "running" && (
            <span className="flex items-center gap-1 text-[11px] text-amber-500 font-medium">
              <Loader2 className="size-3 animate-spin" /> 执行中
            </span>
          )}
          {tool.status === "completed" && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-500 font-medium">
              <CheckCircle2 className="size-3" /> 完成
            </span>
          )}
          {tool.status === "error" && (
            <span className="flex items-center gap-1 text-[11px] text-rose-500 font-medium">
              <XCircle className="size-3" /> 失败
            </span>
          )}
          {isOpen ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />}
        </div>
      </div>

      {isOpen && (
        <div className="border-t border-border/50 bg-muted/20 p-3 font-mono text-[11px] space-y-2">
          {tool.args && (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                参数 (Parameters)
              </div>
              <pre className="overflow-x-auto rounded bg-background/80 p-2 text-muted-foreground whitespace-pre-wrap">
                {typeof tool.args === "string" ? tool.args : JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          )}

          {tool.result && (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                输出结果 (Output)
              </div>
              <pre className={cn(
                "max-h-60 overflow-y-auto rounded bg-background/80 p-2 whitespace-pre-wrap",
                tool.status === "error" ? "text-rose-400" : "text-foreground/90"
              )}>
                {tool.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
