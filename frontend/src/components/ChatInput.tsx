import React, { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { ArrowUp, Sparkles, Square, Zap } from 'lucide-react';

interface ChatInputProps {
  onSend: (text: string) => void;
  onCancel: () => void;
  isGenerating: boolean;
  disabled?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  onCancel,
  isGenerating,
  disabled,
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
      <div className="relative rounded-3xl border border-neutral-200/80 dark:border-white/10 bg-white/80 dark:bg-neutral-900/80 backdrop-blur-2xl shadow-xl shadow-purple-500/[0.03] focus-within:border-purple-500/50 focus-within:ring-4 focus-within:ring-purple-500/10 transition-all">
        {/* 输入文本框 */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向 Lion 派发任务或提问，输入 / 触发命令或技能..."
          rows={1}
          disabled={disabled}
          className="w-full bg-transparent px-5 pt-4 pb-12 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 resize-none focus:outline-none min-h-[56px] max-h-[180px] leading-relaxed"
        />

        {/* 底部操作栏 */}
        <div className="absolute bottom-2.5 left-4 right-3 flex items-center justify-between pointer-events-none">
          {/* 快捷技能标签 */}
          <div className="flex items-center gap-1.5 pointer-events-auto">
            <button
              onClick={() => setInput('/plan ')}
              className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-neutral-100 dark:bg-white/[0.05] hover:bg-neutral-200 dark:hover:bg-white/[0.1] text-neutral-500 dark:text-neutral-400 text-[11px] font-mono transition-colors"
            >
              <Sparkles className="w-3 h-3 text-purple-400" />
              <span>/plan</span>
            </button>
            <button
              onClick={() => setInput('/cost')}
              className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-neutral-100 dark:bg-white/[0.05] hover:bg-neutral-200 dark:hover:bg-white/[0.1] text-neutral-500 dark:text-neutral-400 text-[11px] font-mono transition-colors"
            >
              <Zap className="w-3 h-3 text-amber-400" />
              <span>/cost</span>
            </button>
          </div>

          {/* 发送 / 停止按钮 */}
          <div className="flex items-center gap-2 pointer-events-auto">
            {isGenerating ? (
              <button
                onClick={onCancel}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-rose-500/10 text-rose-500 hover:bg-rose-500/20 text-xs font-semibold border border-rose-500/20 transition-all active:scale-95"
                title="停止生成"
              >
                <Square className="w-3 h-3 fill-current" />
                <span>停止</span>
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() || disabled}
                className={`p-2 rounded-full transition-all active:scale-95 ${
                  input.trim() && !disabled
                    ? 'bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white shadow-md shadow-purple-500/25 cursor-pointer'
                    : 'bg-neutral-100 dark:bg-white/[0.06] text-neutral-400 cursor-not-allowed'
                }`}
                title="发送消息 (Enter)"
              >
                <ArrowUp className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
