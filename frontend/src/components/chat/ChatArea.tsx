import React, { useEffect, useRef, useState } from "react";
import { MessageItem } from "./MessageItem";
import { ChatMessage } from "@/types/chat";
import { Code2, Bug, FileText, Sparkles, ArrowDown } from "lucide-react";

interface ChatAreaProps {
  messages: ChatMessage[];
  onSelectPrompt: (prompt: string) => void;
}

const STARTER_PROMPTS = [
  {
    title: "分析项目架构与分层边界",
    label: "检查 Core / Application / Supervisor 架构契约",
    icon: Code2,
    prompt: "帮我分析一下当前项目的代码架构分层，特别是 Core 与 Application 层的边界。",
  },
  {
    title: "运行质量门禁与测试扫描",
    label: "执行 pytest 与 ruff 门禁检查",
    icon: Bug,
    prompt: "请帮我运行项目的单元测试和架构测试，并检查是否有任何违规报错。",
  },
  {
    title: "制定功能规划 (Plan 模式)",
    label: "进入只读 Plan 模式构思重构方案",
    icon: FileText,
    prompt: "我想对当前项目的模块进行功能扩展，请帮我梳理一个完整的实施计划。",
  },
  {
    title: "快速问答与功能探索",
    label: "询问代码用法与本地环境状态",
    icon: Sparkles,
    prompt: "你好！请向我介绍一下你能做些什么？",
  },
];

export function ChatArea({ messages, onSelectPrompt }: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 120;
    setShowScrollBottom(!isNearBottom);
  };

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-6 text-center select-none">
        <div className="max-w-xl space-y-6">
          <div className="space-y-2">
            <div className="inline-flex size-14 items-center justify-center rounded-2xl bg-blue-500/10 text-blue-600 dark:text-blue-400 shadow-inner border border-blue-500/20">
              <span className="text-3xl">🦁</span>
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
              Hello! How can I help you today?
            </h2>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 max-w-md mx-auto">
              Lion Code 是你的本地极速智能编码 Agent，支持代码重构、终端执行与多轮流式交互。
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
            {STARTER_PROMPTS.map((item, index) => {
              const Icon = item.icon;
              return (
                <button
                  key={index}
                  type="button"
                  onClick={() => onSelectPrompt(item.prompt)}
                  className="group flex flex-col gap-1.5 rounded-2xl border border-zinc-200 dark:border-zinc-800/90 bg-white dark:bg-zinc-900/60 p-4 text-left transition hover:border-blue-500/40 hover:bg-zinc-50/80 dark:hover:bg-zinc-800/60 shadow-xs hover:shadow-md"
                >
                  <div className="flex items-center gap-2 font-semibold text-zinc-900 dark:text-zinc-100 text-xs">
                    <div className="flex size-6 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 group-hover:scale-110 transition-transform">
                      <Icon className="size-3.5" />
                    </div>
                    <span>{item.title}</span>
                  </div>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400 line-clamp-2 leading-relaxed">
                    {item.label}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="relative flex-1 overflow-y-auto"
    >
      <div className="mx-auto max-w-4xl divide-y divide-zinc-100 dark:divide-zinc-800/40 py-4">
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        <div ref={bottomRef} className="h-6" />
      </div>

      {/* 回到底部浮动按钮 */}
      {showScrollBottom && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="fixed bottom-24 right-8 z-30 flex size-9 items-center justify-center rounded-full border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-300 shadow-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 transition animate-in fade-in"
          title="回到底部"
        >
          <ArrowDown className="size-4" />
        </button>
      )}
    </div>
  );
}
