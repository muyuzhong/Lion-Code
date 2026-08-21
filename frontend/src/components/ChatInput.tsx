import React, { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { ArrowUp, Bot, Brain, Sparkles, Square, Trash2, Zap } from 'lucide-react';

interface ChatInputProps {
  onSend: (text: string) => void;
  onCancel: () => void;
  isGenerating: boolean;
  disabled?: boolean;
  currentModel?: string;
  thinkingLevel?: string;
  onThinkingClick?: () => void;
  onClearChat?: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  onCancel,
  isGenerating,
  disabled,
  currentModel,
  thinkingLevel,
  onThinkingClick,
  onClearChat,
}) => {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isGenerating && input.trim()) {
        onSend(input);
        setInput('');
      }
    }
  };

  const handleSend = () => {
    if (input.trim() && !isGenerating) {
      onSend(input);
      setInput('');
    }
  };

  return (
    <div className="relative max-w-3xl mx-auto w-full px-4 mb-4 select-none">
      <div className="relative rounded-3xl border border-neutral-200/80 dark:border-white/10 bg-white/80 dark:bg-[#15151c]/90 backdrop-blur-2xl shadow-2xl shadow-purple-500/[0.05] focus-within:border-purple-500/50 focus-within:ring-4 focus-within:ring-purple-500/10 transition-all">
        {/* 顶部工具条 (LobeChat 标志性快捷工具行) */}
        <div className="flex items-center justify-between px-4 pt-2.5 pb-1 border-b border-neutral-100 dark:border-white/[0.04] text-xs">
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* 当前模型标识 */}
            {currentModel && (
              <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-neutral-100 dark:bg-white/[0.05] text-neutral-600 dark:text-neutral-300 text-[11px] font-medium border border-neutral-200/50 dark:border-white/5">
                <Bot className="w-3 h-3 text-purple-400" />
                <span className="truncate max-w-[120px]">{currentModel}</span>
              </span>
            )}

            {/* Thinking 快捷开关 */}
            {thinkingLevel && onThinkingClick && (
              <button
                type="button"
                onClick={onThinkingClick}
                className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-neutral-100 dark:bg-white/[0.05] hover:bg-purple-500/10 text-neutral-600 dark:text-neutral-300 hover:text-purple-400 text-[11px] font-medium border border-neutral-200/50 dark:border-white/5 transition-colors"
                title="点击切换思考档位"
              >
                <Brain className="w-3 h-3 text-amber-400" />
                <span>Thinking: {thinkingLevel}</span>
              </button>
            )}

            {/* /plan 快捷按钮 */}
            <button
              type="button"
              onClick={() => setInput('/plan ')}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-neutral-100 dark:bg-white/[0.05] hover:bg-purple-500/10 text-neutral-500 dark:text-neutral-400 hover:text-purple-400 text-[11px] font-mono transition-colors border border-transparent hover:border-purple-500/20"
            >
              <Sparkles className="w-3 h-3 text-purple-400" />
              <span>/plan</span>
            </button>

            {/* /cost 快捷按钮 */}
            <button
              type="button"
              onClick={() => setInput('/cost')}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-neutral-100 dark:bg-white/[0.05] hover:bg-purple-500/10 text-neutral-500 dark:text-neutral-400 hover:text-amber-400 text-[11px] font-mono transition-colors border border-transparent hover:border-amber-500/20"
            >
              <Zap className="w-3 h-3 text-amber-400" />
              <span>/cost</span>
            </button>
          </div>

          {/* 清屏图标 */}
          {onClearChat && (
            <button
              type="button"
              onClick={onClearChat}
              className="p-1 rounded-lg text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-white/[0.05] transition-colors"
              title="清空当前消息列表"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* 核心输入框 */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向 Lion 派发任务或提问，输入 / 触发命令或技能..."
          rows={1}
          disabled={disabled}
          className="w-full bg-transparent px-5 pt-3.5 pb-12 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 resize-none focus:outline-none min-h-[52px] max-h-[180px] leading-relaxed"
        />

        {/* 底部右侧发送按钮 */}
        <div className="absolute bottom-3 right-3 flex items-center gap-2">
          {isGenerating ? (
            <button
              onClick={onCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-rose-500/10 text-rose-500 hover:bg-rose-500/20 text-xs font-semibold border border-rose-500/20 transition-all active:scale-95 shadow-sm"
              title="停止生成"
            >
              <Square className="w-3 h-3 fill-current" />
              <span>停止</span>
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-neutral-400 font-mono hidden sm:inline select-none">
                Enter 发送
              </span>
              <button
                onClick={handleSend}
                disabled={!input.trim() || disabled}
                className={`p-2 rounded-full transition-all active:scale-95 ${
                  input.trim() && !disabled
                    ? 'bg-gradient-to-tr from-[#693fe9] to-[#8c52ff] hover:from-[#5e37d4] hover:to-[#7b45e5] text-white shadow-lg shadow-purple-500/30 cursor-pointer'
                    : 'bg-neutral-100 dark:bg-white/[0.06] text-neutral-400 cursor-not-allowed'
                }`}
                title="发送 (Enter)"
              >
                <ArrowUp className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
