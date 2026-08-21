import { useState } from "react";
import { ChevronDown, ChevronRight, Brain } from "lucide-react";

interface ReasoningViewProps {
  reasoning: string;
  isStreaming?: boolean;
}

export function ReasoningView({ reasoning, isStreaming }: ReasoningViewProps) {
  const [isOpen, setIsOpen] = useState<boolean>(true);

  if (!reasoning) return null;

  return (
    <div className="mb-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 text-xs overflow-hidden shadow-2xs">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between px-3.5 py-2 text-zinc-600 dark:text-zinc-400 transition hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40"
      >
        <div className="flex items-center gap-2 font-medium">
          <Brain className={`size-3.5 ${isStreaming ? "animate-pulse text-blue-500" : "text-zinc-500"}`} />
          <span>思考过程 {isStreaming && <span className="text-[10px] text-blue-500 font-mono">(思考中...)</span>}</span>
        </div>
        {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
      </button>

      {isOpen && (
        <div className="border-t border-zinc-200 dark:border-zinc-800/80 px-3.5 py-2.5 text-zinc-600 dark:text-zinc-300 font-mono text-[11px] leading-relaxed whitespace-pre-wrap select-text bg-white/60 dark:bg-zinc-950/40">
          {reasoning}
        </div>
      )}
    </div>
  );
}
