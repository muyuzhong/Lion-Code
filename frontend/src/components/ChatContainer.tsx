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
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center max-w-2xl mx-auto select-none">
        <div className="w-12 h-12 rounded-2xl bg-neutral-100 dark:bg-neutral-800/80 flex items-center justify-center text-2xl shadow-sm mb-4">
          🦁
        </div>
        <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-1">
          Lion Code
        </h2>
        <p className="text-xs text-neutral-500 max-w-md mb-8">
          轻量级编码 Agent，支持多轮流式推理、代码读写与执行、危险命令安全阻断与 Plan 规划模式。
        </p>

        {/* 快速入门卡片 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full text-left">
          <button
            onClick={() => onPromptClick('帮我检查当前项目的架构契约与测试覆盖率')}
            className="p-3 rounded-xl border border-neutral-200/80 dark:border-neutral-800 bg-white/50 dark:bg-neutral-900/40 hover:bg-white dark:hover:bg-neutral-900 hover:border-neutral-300 dark:hover:border-neutral-700 transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-medium text-neutral-800 dark:text-neutral-200 mb-1">
              <Terminal className="w-3.5 h-3.5 text-blue-500" />
              <span>运行架构门禁</span>
            </div>
            <p className="text-[11px] text-neutral-400">
              检查当前目录下的 import-linter 与架构测试
            </p>
          </button>

          <button
            onClick={() => onPromptClick('帮我分析当前目录下的代码结构并输出摘要')}
            className="p-3 rounded-xl border border-neutral-200/80 dark:border-neutral-800 bg-white/50 dark:bg-neutral-900/40 hover:bg-white dark:hover:bg-neutral-900 hover:border-neutral-300 dark:hover:border-neutral-700 transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-medium text-neutral-800 dark:text-neutral-200 mb-1">
              <Code2 className="w-3.5 h-3.5 text-amber-500" />
              <span>分析代码库</span>
            </div>
            <p className="text-[11px] text-neutral-400">
              扫描项目核心模块与各层依赖关系
            </p>
          </button>

          <button
            onClick={() => onPromptClick('/plan 接下来我们需要实现什么功能')}
            className="p-3 rounded-xl border border-neutral-200/80 dark:border-neutral-800 bg-white/50 dark:bg-neutral-900/40 hover:bg-white dark:hover:bg-neutral-900 hover:border-neutral-300 dark:hover:border-neutral-700 transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-medium text-neutral-800 dark:text-neutral-200 mb-1">
              <Sparkles className="w-3.5 h-3.5 text-purple-500" />
              <span>开启 Plan 模式</span>
            </div>
            <p className="text-[11px] text-neutral-400">
              只读规划方案，审批后方可执行改动
            </p>
          </button>

          <button
            onClick={() => onPromptClick('/cost')}
            className="p-3 rounded-xl border border-neutral-200/80 dark:border-neutral-800 bg-white/50 dark:bg-neutral-900/40 hover:bg-white dark:hover:bg-neutral-900 hover:border-neutral-300 dark:hover:border-neutral-700 transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-medium text-neutral-800 dark:text-neutral-200 mb-1">
              <Wrench className="w-3.5 h-3.5 text-emerald-500" />
              <span>查看消耗与用量</span>
            </div>
            <p className="text-[11px] text-neutral-400">
              获取当前会话的 Token 用量与统计
            </p>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-3xl mx-auto">
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        <div ref={bottomRef} className="h-4" />
      </div>
    </div>
  );
};
