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
      <div className="flex justify-end gap-3 my-4 group">
        <div className="max-w-[85%] sm:max-w-2xl bg-neutral-900 dark:bg-neutral-100 text-neutral-100 dark:text-neutral-900 rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm text-sm">
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        </div>
        <div className="w-8 h-8 rounded-full bg-neutral-200 dark:bg-neutral-800 flex items-center justify-center flex-shrink-0 text-neutral-600 dark:text-neutral-300">
          <User className="w-4 h-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3.5 my-6 group">
      {/* 头像 */}
      <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-amber-500 to-orange-500 flex items-center justify-center flex-shrink-0 text-white shadow-sm mt-1">
        <span className="text-sm select-none">🦁</span>
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
          <div className="my-2 space-y-1">
            {message.tools.map((tool) => (
              <ToolCallCard key={tool.id} tool={tool} />
            ))}
          </div>
        )}

        {/* Markdown 回复正文 */}
        {message.content ? (
          <div className="prose prose-sm dark:prose-invert max-w-none text-neutral-900 dark:text-neutral-100 leading-relaxed font-sans text-sm break-words">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        ) : message.tools?.length === 0 && !message.thinking ? (
          <div className="flex items-center gap-1.5 text-neutral-400 text-xs py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-neutral-400 animate-pulse" />
            <span className="w-1.5 h-1.5 rounded-full bg-neutral-400 animate-pulse delay-75" />
            <span className="w-1.5 h-1.5 rounded-full bg-neutral-400 animate-pulse delay-150" />
          </div>
        ) : null}

        {/* 操作工具栏 */}
        {message.content && (
          <div className="flex items-center gap-2 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={handleCopy}
              className="p-1 rounded text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 transition-colors"
              title="复制回答"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
