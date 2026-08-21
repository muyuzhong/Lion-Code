import React, { useState } from 'react';
import { Check, Copy, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatMessage } from '../types';
import { ThinkingAccordion } from './ThinkingAccordion';
import { ToolCallCard } from './ToolCallCard';

interface MessageItemProps {
  message: ChatMessage;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message }) => {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isUser) {
    return (
      <div className="flex justify-end gap-3 my-6 group">
        <div className="flex flex-col items-end max-w-[85%] sm:max-w-2xl">
          <div className="bg-[#1e2a44] border border-[#32456e] text-slate-100 rounded-2xl rounded-tr-sm px-4 py-3 shadow-md text-sm leading-relaxed whitespace-pre-wrap">
            {message.content}
          </div>
          <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <span>{new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          </div>
        </div>

        {/* User 头像 */}
        <div className="w-9 h-9 rounded-2xl bg-[#161e31] flex items-center justify-center flex-shrink-0 text-slate-300 shadow-sm mt-0.5 border border-white/10">
          <User className="w-4 h-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3.5 my-6 group">
      {/* DeepSeek Harness 官方蓝头像 */}
      <div className="relative flex-shrink-0 mt-0.5">
        <div className="w-9 h-9 rounded-2xl bg-gradient-to-tr from-[#4e75ff] to-[#3b82f6] p-[1.5px] shadow-lg shadow-blue-500/25">
          <div className="w-full h-full rounded-[14px] bg-[#121827] flex items-center justify-center text-base select-none">
            🐋
          </div>
        </div>
      </div>

      {/* 消息主体 */}
      <div className="flex-1 min-w-0">
        {/* 头部信息 */}
        <div className="flex items-center gap-2 mb-1 select-none">
          <span className="text-xs font-semibold text-slate-100 flex items-center gap-1">
            DeepSeek Harness
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#4e75ff]/15 text-[#4e75ff] font-medium border border-[#4e75ff]/30">
            Agent
          </span>
          <span className="text-[10px] text-slate-500 font-mono">
            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>

        {/* Thinking 思考过程折叠 */}
        {message.thinking || message.isThinkingActive ? (
          <ThinkingAccordion
            thinking={message.thinking || ''}
            isActive={message.isThinkingActive}
          />
        ) : null}

        {/* Tool 调用卡片 */}
        {message.tools && message.tools.length > 0 && (
          <div className="my-2 space-y-1">
            {message.tools.map((tool) => (
              <ToolCallCard key={tool.id} tool={tool} />
            ))}
          </div>
        )}

        {/* Markdown 回复正文 (DSH 风格) */}
        {message.content ? (
          <div className="p-4 rounded-2xl rounded-tl-sm bg-[#161e31]/90 border border-white/[0.08] shadow-sm backdrop-blur-md">
            <div className="prose prose-sm prose-invert max-w-none text-slate-200 leading-relaxed font-sans text-sm break-words">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          </div>
        ) : message.tools?.length === 0 && !message.thinking ? (
          <div className="flex items-center gap-2 text-slate-400 text-xs py-3 px-4 rounded-2xl bg-[#161e31]/50 border border-white/[0.06]">
            <span className="w-2 h-2 rounded-full bg-[#4e75ff] animate-ping" />
            <span className="text-slate-400 font-mono text-[11px]">DeepSeek Harness 正在推理回答...</span>
          </div>
        ) : null}

        {/* 底部悬浮操作栏 */}
        {message.content && (
          <div className="flex items-center gap-1 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity select-none">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.06] text-[11px] transition-colors"
              title="复制回答"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400 font-medium">已复制</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>复制</span>
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
