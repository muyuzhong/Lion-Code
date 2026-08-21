import React, { useEffect, useRef } from "react";
import { MessageItem } from "./MessageItem";
import { ChatMessage } from "@/types/chat";
import { Code2, Bug, FileText, Sparkles } from "lucide-react";

interface ChatAreaProps {
  messages: ChatMessage[];
  onSelectPrompt: (prompt: string) => void;
}

const STARTER_PROMPTS = [
  {
    title: "分析项目架构与分层边界",
    label: "检查当前项目的 Core / Application / Supervisor 边界契约",
    icon: Code2,
    prompt: "帮我分析一下当前项目的代码架构分层，特别是 Core 与 Application 层的边界。",
  },
  {
    title: "启动代码质量门禁扫描",
    label: "运行 pytest 与 ruff 门禁测试",
    icon: Bug,
    prompt: "请帮我运行项目的单元测试和架构测试，并检查是否有违规报错。",
  },
  {
    title: "制定功能重构计划 (Plan)",
    label: "进入 Plan 模式构思设计方案",
    icon: FileText,
    prompt: "我想对当前项目的模块进行功能扩展，请帮我梳理一个完整的实施计划。",
  },
  {
    title: "快速问答与辅助编码",
    label: "询问任何开发与代码问题",
    icon: Sparkles,
    prompt: "你好！请向我介绍一下你能做些什么？",
  },
];

export function ChatArea({ messages, onSelectPrompt }: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
        <div className="max-w-xl space-y-6">
          <div className="space-y-2">
            <div className="inline-flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-inner">
              <span className="text-2xl">🦁</span>
            </div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Hello! How can I help you today?
            </h2>
            <p className="text-sm text-muted-foreground">
              Lion Code 是你的轻量级智能编码 Agent，支持终端执行、代码重构与多轮对话。
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
                  className="flex flex-col gap-1 rounded-xl border border-border/80 bg-card p-3.5 text-left transition hover:border-primary/50 hover:bg-muted/50 shadow-xs"
                >
                  <div className="flex items-center gap-2 font-medium text-foreground text-xs">
                    <Icon className="size-3.5 text-primary" />
                    <span>{item.title}</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground line-clamp-2">
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
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl divide-y divide-border/20 py-4">
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        <div ref={bottomRef} className="h-4" />
      </div>
    </div>
  );
}
