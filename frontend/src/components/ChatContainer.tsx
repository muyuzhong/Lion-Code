import React, { useEffect, useRef } from 'react';
import { Code2, Sparkles, Terminal, Wrench } from 'lucide-react';
import { ChatMessage } from '../types';
import { MessageItem } from './MessageItem';

interface ChatContainerProps {
  messages: ChatMessage[];
  onPromptClick: (prompt: string) => void;
}

export const ChatContainer: React.FC<ChatContainerProps> = ({ messages, onPromptClick }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center max-w-3xl mx-auto select-none lobe-ambient-glow">
        {/* Lion 头像光环 */}
        <div className="relative mb-5 group">
          <div className="w-16 h-16 rounded-3xl bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-600 p-[2px] shadow-2xl shadow-purple-500/30 transition-transform group-hover:scale-105">
            <div className="w-full h-full rounded-[22px] bg-neutral-900 flex items-center justify-center text-3xl shadow-inner">
              🦁
            </div>
          </div>
        </div>

        <h2 className="text-xl font-bold tracking-tight text-neutral-900 dark:text-white mb-1.5 bg-gradient-to-r from-neutral-900 via-purple-600 to-indigo-600 dark:from-white dark:via-purple-300 dark:to-indigo-300 bg-clip-text text-transparent">
          Lion Code
        </h2>
        <p className="text-xs text-neutral-500 dark:text-neutral-400 max-w-md mb-8 leading-relaxed">
          极致轻量、高可观测的自主编码 Agent，基于全新 Lobe 交互与全双工流式架构。
        </p>

        {/* 快捷入门卡片 (Lobe 风格卡片) */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full text-left">
          <button
            onClick={() => onPromptClick('帮我检查当前项目的架构契约与测试覆盖率')}
            className="p-4 rounded-2xl border border-neutral-200/80 dark:border-white/10 bg-white/60 dark:bg-white/[0.03] hover:bg-white dark:hover:bg-white/[0.06] lobe-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-neutral-800 dark:text-neutral-200 mb-1">
              <div className="p-1 rounded-lg bg-blue-500/10 text-blue-500">
                <Terminal className="w-4 h-4" />
              </div>
              <span>架构门禁扫描</span>
            </div>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
              运行 138 项 import-linter 契约与运行时边界测试
            </p>
          </button>

          <button
            onClick={() => onPromptClick('帮我分析当前目录下的代码结构并输出摘要')}
            className="p-4 rounded-2xl border border-neutral-200/80 dark:border-white/10 bg-white/60 dark:bg-white/[0.03] hover:bg-white dark:hover:bg-white/[0.06] lobe-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-neutral-800 dark:text-neutral-200 mb-1">
              <div className="p-1 rounded-lg bg-amber-500/10 text-amber-500">
                <Code2 className="w-4 h-4" />
              </div>
              <span>代码拓扑分析</span>
            </div>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
              梳理 Lion 各分层职责与核心模块数据流
            </p>
          </button>

          <button
            onClick={() => onPromptClick('/plan 接下来我们需要实现什么功能')}
            className="p-4 rounded-2xl border border-neutral-200/80 dark:border-white/10 bg-white/60 dark:bg-white/[0.03] hover:bg-white dark:hover:bg-white/[0.06] lobe-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-neutral-800 dark:text-neutral-200 mb-1">
              <div className="p-1 rounded-lg bg-purple-500/10 text-purple-500">
                <Sparkles className="w-4 h-4" />
              </div>
              <span>启动 Plan 规划</span>
            </div>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
              进入只读分析模式，生成详细改造方案并等待审批
            </p>
          </button>

          <button
            onClick={() => onPromptClick('/cost')}
            className="p-4 rounded-2xl border border-neutral-200/80 dark:border-white/10 bg-white/60 dark:bg-white/[0.03] hover:bg-white dark:hover:bg-white/[0.06] lobe-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-neutral-800 dark:text-neutral-200 mb-1">
              <div className="p-1 rounded-lg bg-emerald-500/10 text-emerald-500">
                <Wrench className="w-4 h-4" />
              </div>
              <span>Token 统计与消耗</span>
            </div>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
              实时查询当前会话的输入/输出 Token 消耗
            </p>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 lobe-ambient-glow">
      <div className="max-w-3xl mx-auto">
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        <div ref={bottomRef} className="h-4" />
      </div>
    </div>
  );
};
