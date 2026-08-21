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
          <div className="bg-gradient-to-tr from-[#693fe9] to-[#8c52ff] text-white rounded-2xl rounded-tr-sm px-4 py-3 shadow-lg shadow-purple-500/15 text-sm leading-relaxed whitespace-pre-wrap selection:bg-purple-900 selection:text-white">
            {message.content}
          </div>
          <div className="flex items-center gap-2 text-[10px] text-neutral-400 font-mono mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <span>{new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          </div>
        </div>

        {/* User 头像 */}
        <div className="w-9 h-9 rounded-2xl bg-neutral-200 dark:bg-neutral-800 flex items-center justify-center flex-shrink-0 text-neutral-600 dark:text-neutral-300 shadow-sm mt-0.5 border border-neutral-300/40 dark:border-neutral-700/50">
          <User className="w-4 h-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3.5 my-6 group">
      {/* Lion Assistant 头像 (Lobe 风格渐变外框) */}
      <div className="relative flex-shrink-0 mt-0.5">
        <div className="w-9 h-9 rounded-2xl bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-600 p-[1.5px] shadow-lg shadow-purple-500/25">
          <div className="w-full h-full rounded-[14px] bg-neutral-900 flex items-center justify-center text-base select-none">
            🦁
          </div>
        </div>
      </div>

      {/* 消息主体 */}
      <div className="flex-1 min-w-0">
        {/* 头部信息 */}
        <div className="flex items-center gap-2 mb-1 select-none">
          <span className="text-xs font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-1">
            Lion Code
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-purple-500/10 text-purple-600 dark:text-purple-400 font-medium border border-purple-500/20">
            Agent
          </span>
          <span className="text-[10px] text-neutral-400 font-mono">
            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>

        {/* Thinking 思考链折叠 */}
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

        {/* Markdown 回复正文 (Lobe 风格气泡与代码块) */}
        {message.content ? (
          <div className="p-4 rounded-2xl rounded-tl-sm bg-white/70 dark:bg-white/[0.04] border border-neutral-200/80 dark:border-white/[0.08] shadow-sm backdrop-blur-md">
            <div className="prose prose-sm dark:prose-invert max-w-none text-neutral-900 dark:text-neutral-100 leading-relaxed font-sans text-sm break-words">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          </div>
        ) : message.tools?.length === 0 && !message.thinking ? (
          <div className="flex items-center gap-2 text-neutral-400 text-xs py-3 px-4 rounded-2xl bg-white/40 dark:bg-white/[0.02] border border-neutral-200/50 dark:border-white/[0.05]">
            <span className="w-2 h-2 rounded-full bg-purple-500 animate-ping" />
            <span className="text-neutral-400 font-mono text-[11px]">Lion 正在生成思考与回答...</span>
          </div>
        ) : null}

        {/* 底部悬浮操作栏 (Lobe 风格) */}
        {message.content && (
          <div className="flex items-center gap-1 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity select-none">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 hover:bg-neutral-200/50 dark:hover:bg-white/[0.08] text-[11px] transition-colors"
              title="复制完整回答"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                  <span className="text-emerald-500 font-medium">已复制</span>
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
