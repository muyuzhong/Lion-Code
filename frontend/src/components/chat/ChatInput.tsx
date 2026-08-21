import React, { useState, useRef, useEffect } from "react";
import { ArrowUp, Square, Paperclip, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSendMessage: (text: string) => void;
  onCancel: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export function ChatInput({ onSendMessage, onCancel, isStreaming, disabled }: ChatInputProps) {
  const [input, setInput] = useState<string>("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isStreaming && input.trim()) {
        onSendMessage(input);
        setInput("");
        if (textareaRef.current) {
          textareaRef.current.style.height = "auto";
        }
      }
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isStreaming) {
      onCancel();
      return;
    }
    if (input.trim()) {
      onSendMessage(input);
      setInput("");
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    }
  };

  return (
    <div className="border-t border-border/40 bg-background/95 px-4 pb-4 pt-2 backdrop-blur-sm">
      <form onSubmit={handleSubmit} className="mx-auto max-w-4xl">
        <div className="relative flex flex-col rounded-2xl border border-border/80 bg-muted/30 shadow-xs focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-primary/40 transition">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            disabled={disabled}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题或指令... (Enter 发送, Shift+Enter 换行)"
            className="w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden"
          />

          <div className="flex items-center justify-between px-3 py-2 border-t border-border/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <button
                type="button"
                className="flex items-center gap-1 rounded-md px-2 py-1 hover:bg-muted text-[11px] transition text-muted-foreground hover:text-foreground"
                onClick={() => setInput((prev) => prev + " @")}
              >
                <Paperclip className="size-3" />
                <span>引用文件</span>
              </button>
              <button
                type="button"
                className="flex items-center gap-1 rounded-md px-2 py-1 hover:bg-muted text-[11px] transition text-muted-foreground hover:text-foreground"
                onClick={() => setInput("/plan ")}
              >
                <Sparkles className="size-3 text-amber-500" />
                <span>Plan 模式</span>
              </button>
            </div>

            <div className="flex items-center gap-2">
              {isStreaming ? (
                <button
                  type="button"
                  onClick={onCancel}
                  className="flex size-7.5 items-center justify-center rounded-full bg-destructive text-destructive-foreground transition hover:opacity-90 shadow-xs"
                >
                  <Square className="size-3.5 fill-current" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim() || disabled}
                  className={cn(
                    "flex size-7.5 items-center justify-center rounded-full bg-primary text-primary-foreground transition shadow-xs",
                    (!input.trim() || disabled) && "opacity-40 cursor-not-allowed"
                  )}
                >
                  <ArrowUp className="size-4" />
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="mt-1.5 text-center text-[10px] text-muted-foreground/60">
          Lion Code 正在运行于本地环境，受架构契约与权限边界保护。
        </div>
      </form>
    </div>
  );
}
