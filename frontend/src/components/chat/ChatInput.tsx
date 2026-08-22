import React, { useState, useRef, useEffect } from "react";
import { ArrowUp, Square, Paperclip, Sparkles, CornerUpRight, Hourglass } from "lucide-react";

interface ChatInputProps {
  // 非流式：按 prompt 发起新一轮
  onSendMessage: (text: string) => void;
  // 流式：Enter / 主发送按钮语义（D1），排队等当前轮结束
  onFollowUp: (text: string) => void;
  // 流式：立即转向（D8，显式次级按钮，不做模式切换）
  onSteer: (text: string) => void;
  onCancel: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  // 已排队总数（steering + followUp），来自 queue_update 快照（D7）
  queueCount?: number;
  // 侧边栏 skill 引用等外部注入的草稿；父组件每次传入新对象引用即覆盖当前输入并聚焦
  prefill?: { text: string } | null;
}

export function ChatInput({
  onSendMessage,
  onFollowUp,
  onSteer,
  onCancel,
  isStreaming,
  disabled,
  queueCount = 0,
  prefill,
}: ChatInputProps) {
  const [input, setInput] = useState<string>("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

  useEffect(() => {
    if (!prefill) return;
    setInput(prefill.text);
    textareaRef.current?.focus();
  }, [prefill]);

  const submitInput = () => {
    if (!input.trim()) return;
    if (isStreaming) {
      onFollowUp(input);
    } else {
      onSendMessage(input);
    }
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitInput();
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submitInput();
  };

  const handleSteer = () => {
    if (!input.trim()) return;
    onSteer(input);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 bg-white/95 dark:bg-zinc-950/95 px-4 pb-4 pt-2 backdrop-blur-sm transition-colors">
      <form onSubmit={handleSubmit} className="mx-auto max-w-4xl">
        {queueCount > 0 && (
          <div className="mb-1.5 flex justify-end">
            <span className="inline-flex items-center gap-1 rounded-full border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 px-2 py-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
              <Hourglass className="size-3" />
              <span>已排队 ×{queueCount}</span>
            </span>
          </div>
        )}
        <div className="relative flex flex-col rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/60 shadow-xs focus-within:border-zinc-400 dark:focus-within:border-zinc-600 focus-within:ring-1 focus-within:ring-zinc-400 dark:focus-within:ring-zinc-600 transition">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            disabled={disabled}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isStreaming
                ? "正在运行中… Enter 排队跟进，等待本轮结束后执行"
                : "输入你的问题或指令... (Enter 发送, Shift+Enter 换行)"
            }
            className="w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-sm text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 focus:outline-hidden"
          />

          <div className="flex items-center justify-between px-3 py-2 border-t border-zinc-200/60 dark:border-zinc-800/60">
            <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              <button
                type="button"
                className="flex items-center gap-1 rounded-md px-2 py-1 hover:bg-zinc-200/60 dark:hover:bg-zinc-800 text-[11px] transition text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                onClick={() => setInput((prev) => prev + " @")}
              >
                <Paperclip className="size-3" />
                <span>引用文件</span>
              </button>
              <button
                type="button"
                disabled={disabled || isStreaming}
                className="flex items-center gap-1 rounded-md px-2 py-1 hover:bg-zinc-200/60 dark:hover:bg-zinc-800 text-[11px] transition text-amber-600 dark:text-amber-400 font-medium disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => onSendMessage("/plan")}
              >
                <Sparkles className="size-3" />
                <span>Plan 模式</span>
              </button>
            </div>

            <div className="flex items-center gap-2">
              {isStreaming && (
                <button
                  type="button"
                  onClick={handleSteer}
                  disabled={!input.trim() || disabled}
                  title="立即转向：中断当前方向，按此输入改向执行"
                  className="flex size-7.5 items-center justify-center rounded-full border border-zinc-300 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 transition hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <CornerUpRight className="size-4" />
                </button>
              )}
              <button
                type="submit"
                disabled={!input.trim() || disabled}
                className={`flex size-7.5 items-center justify-center rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 transition shadow-xs ${
                  !input.trim() || disabled ? "opacity-30 cursor-not-allowed" : "hover:opacity-90"
                }`}
              >
                <ArrowUp className="size-4" />
              </button>
              {isStreaming && (
                <button
                  type="button"
                  onClick={onCancel}
                  className="flex size-7.5 items-center justify-center rounded-full bg-rose-600 text-white transition hover:bg-rose-500 shadow-xs"
                >
                  <Square className="size-3.5 fill-current" />
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="mt-1.5 text-center text-[10px] text-zinc-400 dark:text-zinc-500">
          Lion Code 正在运行于本地环境，受架构契约与权限边界保护。
        </div>
      </form>
    </div>
  );
}
