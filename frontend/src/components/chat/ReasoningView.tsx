import React, { useState, useEffect, useRef } from "react";
import { ChevronDown, ChevronRight, Brain, Sparkles, Clock, Check } from "lucide-react";

interface ReasoningViewProps {
  reasoning: string;
  isStreaming?: boolean;
}

export function ReasoningView({ reasoning, isStreaming }: ReasoningViewProps) {
  const [isOpen, setIsOpen] = useState<boolean>(true);
  const [seconds, setSeconds] = useState<number>(0);
  const timerRef = useRef<number | null>(null);

  // 记录思考耗时
  useEffect(() => {
    if (isStreaming) {
      setSeconds(0);
      const start = Date.now();
      timerRef.current = window.setInterval(() => {
        setSeconds(Math.floor((Date.now() - start) / 100) / 10);
      }, 100);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [isStreaming]);

  // 当思考结束且内容输出时，保持折叠状态友好
  const [copied, setCopied] = useState(false);
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(reasoning);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!reasoning) return null;

  return (
    <div className="my-2.5 overflow-hidden rounded-xl border border-zinc-200/80 dark:border-zinc-800/80 bg-zinc-50/70 dark:bg-zinc-900/40 text-xs shadow-2xs transition-all">
      {/* 折叠触发条 */}
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex cursor-pointer items-center justify-between px-3.5 py-2 select-none hover:bg-zinc-100/60 dark:hover:bg-zinc-800/50 transition"
      >
        <div className="flex items-center gap-2">
          <div
            className={`flex size-5 items-center justify-center rounded-md ${
              isStreaming
                ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                : "bg-zinc-200/80 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400"
            }`}
          >
            <Brain className={`size-3.5 ${isStreaming ? "animate-pulse" : ""}`} />
          </div>

          <span className="font-medium text-zinc-800 dark:text-zinc-200">
            {isStreaming ? "深度思考中 (Thinking)..." : "思考过程 (Thought Process)"}
          </span>

          {isStreaming ? (
            <span className="flex items-center gap-1 text-[11px] font-mono text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/50 px-1.5 py-0.5 rounded-full border border-blue-200 dark:border-blue-800/60">
              <Clock className="size-3 animate-spin" />
              <span>{seconds.toFixed(1)}s</span>
            </span>
          ) : (
            <span className="text-[11px] text-zinc-400 dark:text-zinc-500 font-mono">
              ({reasoning.length} 字符)
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {isOpen && (
            <button
              type="button"
              onClick={handleCopy}
              className="text-[10px] text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition"
            >
              {copied ? "已复制" : "复制"}
            </button>
          )}
          <div className="text-zinc-400 dark:text-zinc-500">
            {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          </div>
        </div>
      </div>

      {/* 思考正文 */}
      {isOpen && (
        <div className="border-t border-zinc-200/60 dark:border-zinc-800/60 bg-white/50 dark:bg-zinc-950/40 px-4 py-3 font-mono text-[11.5px] leading-relaxed text-zinc-600 dark:text-zinc-300 whitespace-pre-wrap select-text max-h-72 overflow-y-auto">
          {reasoning}
          {isStreaming && (
            <span className="inline-block size-1.5 ml-1 rounded-full bg-blue-500 animate-pulse align-middle" />
          )}
        </div>
      )}
    </div>
  );
}
