import React, { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { ArrowUp, Square } from 'lucide-react';

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

  // 自动调整高度
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
    <div className="relative max-w-3xl mx-auto w-full px-4 mb-4">
      <div className="relative rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900/90 shadow-lg focus-within:ring-1 focus-within:ring-neutral-400 dark:focus-within:ring-neutral-600 transition-all">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向 Lion 提问或派发任务，输入 / 查看可用命令..."
          rows={1}
          disabled={disabled}
          className="w-full bg-transparent px-4 pt-3.5 pb-10 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 resize-none focus:outline-none min-h-[52px] max-h-[180px]"
        />

        {/* 底部按钮栏 */}
        <div className="absolute bottom-2.5 right-3 flex items-center gap-2">
          {isGenerating ? (
            <button
              onClick={onCancel}
              className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-500/20 text-xs font-medium transition-colors"
              title="停止生成"
            >
              <Square className="w-3 h-3 fill-current" />
              <span>停止</span>
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim() || disabled}
              className={`p-1.5 rounded-full transition-all ${
                input.trim() && !disabled
                  ? 'bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 shadow hover:opacity-90'
                  : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-400 cursor-not-allowed'
              }`}
              title="发送消息 (Enter)"
            >
              <ArrowUp className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* 快捷提示 */}
        <div className="absolute bottom-2.5 left-3 text-[10px] text-neutral-400 flex items-center gap-1 select-none">
          <span>按</span>
          <span className="px-1 rounded bg-neutral-100 dark:bg-neutral-800 font-mono text-[9px]">Enter</span>
          <span>发送，</span>
          <span className="px-1 rounded bg-neutral-100 dark:bg-neutral-800 font-mono text-[9px]">Shift+Enter</span>
          <span>换行</span>
        </div>
      </div>
    </div>
  );
};
