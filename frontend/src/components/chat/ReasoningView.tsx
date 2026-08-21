import { useState } from "react";
import { ChevronDown, ChevronRight, Brain } from "lucide-react";
import { cn } from "@/lib/utils";

interface ReasoningViewProps {
  reasoning: string;
  isStreaming?: boolean;
}

export function ReasoningView({ reasoning, isStreaming }: ReasoningViewProps) {
  const [isOpen, setIsOpen] = useState<boolean>(true);

  if (!reasoning) return null;

  return (
    <div className="mb-3 rounded-lg border border-border/60 bg-muted/40 text-xs">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between px-3 py-2 text-muted-foreground transition hover:text-foreground"
      >
        <div className="flex items-center gap-2 font-medium">
          <Brain className={cn("size-3.5", isStreaming && "animate-pulse text-primary")} />
          <span>思考过程 {isStreaming && <span className="text-[10px] text-muted-foreground/80">(思考中...)</span>}</span>
        </div>
        {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
      </button>

      {isOpen && (
        <div className="border-t border-border/40 px-3 py-2 text-muted-foreground/90 font-mono leading-relaxed whitespace-pre-wrap select-text">
          {reasoning}
        </div>
      )}
    </div>
  );
}
