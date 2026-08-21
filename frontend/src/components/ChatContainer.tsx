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
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center max-w-3xl mx-auto select-none dsh-ambient-glow">
        {/* DeepSeek 官方鲸鱼蓝光晕头像 */}
        <div className="relative mb-5 group">
          <div className="w-16 h-16 rounded-3xl bg-gradient-to-tr from-[#4e75ff] via-[#3b82f6] to-[#60a5fa] p-[2px] shadow-2xl shadow-blue-500/35 transition-transform group-hover:scale-105">
            <div className="w-full h-full rounded-[22px] bg-[#101524] flex items-center justify-center text-3xl shadow-inner">
              🐋
            </div>
          </div>
        </div>

        <h2 className="text-xl font-bold tracking-tight text-white mb-1.5 bg-gradient-to-r from-white via-slate-200 to-[#93c5fd] bg-clip-text text-transparent">
          DeepSeek Harness
        </h2>
        <p className="text-xs text-slate-400 max-w-md mb-8 leading-relaxed">
          极致轻量、高可观测的自主编码 Agent，基于 DeepSeek 经典设计规范与全双工流式架构。
        </p>

        {/* 快捷入门卡片 (DSH 风格) */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full text-left">
          <button
            onClick={() => onPromptClick('帮我检查当前项目的架构契约与测试覆盖率')}
            className="p-4 rounded-2xl border border-white/10 bg-[#141b2d]/80 hover:bg-[#1a2338] dsh-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-slate-200 mb-1">
              <div className="p-1 rounded-lg bg-[#4e75ff]/15 text-[#4e75ff]">
                <Terminal className="w-4 h-4" />
              </div>
              <span>架构门禁扫描</span>
            </div>
            <p className="text-[11px] text-slate-400">
              运行 138 项 import-linter 契约与运行时边界测试
            </p>
          </button>

          <button
            onClick={() => onPromptClick('帮我分析当前目录下的代码结构并输出摘要')}
            className="p-4 rounded-2xl border border-white/10 bg-[#141b2d]/80 hover:bg-[#1a2338] dsh-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-slate-200 mb-1">
              <div className="p-1 rounded-lg bg-amber-500/15 text-amber-400">
                <Code2 className="w-4 h-4" />
              </div>
              <span>代码拓扑分析</span>
            </div>
            <p className="text-[11px] text-slate-400">
              梳理 Lion 各分层职责与核心模块数据流
            </p>
          </button>

          <button
            onClick={() => onPromptClick('/plan 接下来我们需要实现什么功能')}
            className="p-4 rounded-2xl border border-white/10 bg-[#141b2d]/80 hover:bg-[#1a2338] dsh-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-slate-200 mb-1">
              <div className="p-1 rounded-lg bg-[#4e75ff]/15 text-[#4e75ff]">
                <Sparkles className="w-4 h-4" />
              </div>
              <span>启动 Plan 规划</span>
            </div>
            <p className="text-[11px] text-slate-400">
              进入只读分析模式，生成详细改造方案并等待审批
            </p>
          </button>

          <button
            onClick={() => onPromptClick('/cost')}
            className="p-4 rounded-2xl border border-white/10 bg-[#141b2d]/80 hover:bg-[#1a2338] dsh-card-hover transition-all text-xs group"
          >
            <div className="flex items-center gap-2 font-semibold text-slate-200 mb-1">
              <div className="p-1 rounded-lg bg-emerald-500/15 text-emerald-400">
                <Wrench className="w-4 h-4" />
              </div>
              <span>Token 统计与消耗</span>
            </div>
            <p className="text-[11px] text-slate-400">
              实时查询当前会话的输入/输出 Token 消耗
            </p>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 dsh-ambient-glow">
      <div className="max-w-3xl mx-auto">
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        <div ref={bottomRef} className="h-4" />
      </div>
    </div>
  );
};
