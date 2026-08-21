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
      <div className="flex justify-end gap-3.5 my-6 group">
        <div className="flex flex-col items-end max-w-[85%] sm:max-w-2xl">
          <div className="bg-gradient-to-tr from-purple-600 to-indigo-600 text-white rounded-3xl rounded-tr-md px-4 py-3 shadow-md shadow-purple-500/10 text-sm leading-relaxed whitespace-pre-wrap">
            {message.content}
          </div>
          <div className="text-[10px] text-neutral-400 font-mono mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        </div>

        {/* User 头像 */}
        <div className="w-8 h-8 rounded-full bg-neutral-200 dark:bg-neutral-800 flex items-center justify-center flex-shrink-0 text-neutral-600 dark:text-neutral-300 shadow-sm mt-0.5">
          <User className="w-4 h-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3.5 my-6 group">
      {/* Lion Assistant 头像 (带微发光光晕) */}
      <div className="relative flex-shrink-0 mt-0.5">
        <div className="w-8 h-8 rounded-2xl bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-600 p-[1.5px] shadow-md shadow-purple-500/20">
          <div className="w-full h-full rounded-[14px] bg-neutral-900 flex items-center justify-center text-sm select-none">
            🦁
          </div>
        </div>
      </div>

      {/* 消息主体 */}
      <div className="flex-1 min-w-0">
        {/* Thinking 思考链折叠 */}
        {message.thinking || message.isThinkingActive ? (
          <ThinkingAccordion
            thinking={message.thinking || ''}
            isActive={message.isThinkingActive}
          />
        ) : null}

        {/* Tool 调用卡片 */}
        {message.tools && message.tools.length > 0 && (
          <div className="my-2.5 space-y-1">
            {message.tools.map((tool) => (
              <ToolCallCard key={tool.id} tool={tool} />
            ))}
          </div>
        )}

        {/* Markdown 回复正文 */}
        {message.content ? (
          <div className="prose prose-sm dark:prose-invert max-w-none text-neutral-900 dark:text-neutral-100 leading-relaxed font-sans text-sm break-words py-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        ) : message.tools?.length === 0 && !message.thinking ? (
          <div className="flex items-center gap-1.5 text-neutral-400 text-xs py-2">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse" />
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse delay-75" />
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse delay-150" />
            <span className="text-neutral-400 font-mono text-[11px] ml-1">Lion 正在生成中...</span>
          </div>
        ) : null}

        {/* 操作工具栏 */}
        {message.content && (
          <div className="flex items-center gap-2 mt-2 opacity-0 group-hover:opacity-100 transition-opacity select-none">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-white/[0.05] text-[11px] transition-colors"
              title="复制回答"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                  <span className="text-emerald-500">已复制</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>复制</span>
                </>
              )}
            </button>
            <span className="text-[10px] font-mono text-neutral-400">
              {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
