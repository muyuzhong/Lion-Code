import React, { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { ArrowUp, AtSign, Bot, Brain, Sparkles, Square, Trash2, Zap } from 'lucide-react';

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
      <div className="relative rounded-3xl border border-white/10 bg-[#161e31]/95 backdrop-blur-2xl shadow-2xl shadow-blue-500/[0.05] focus-within:border-[#4e75ff]/60 focus-within:ring-4 focus-within:ring-[#4e75ff]/10 transition-all">
        {/* 顶部工具行 (DSH 标志性快捷工具栏) */}
        <div className="flex items-center justify-between px-4 pt-2.5 pb-1 border-b border-white/[0.04] text-xs">
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* 当前模型 */}
            {currentModel && (
              <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#1c263e] text-slate-300 text-[11px] font-medium border border-white/5">
                <Bot className="w-3 h-3 text-[#4e75ff]" />
                <span className="truncate max-w-[120px]">{currentModel}</span>
              </span>
            )}

            {/* Thinking 切换 */}
            {thinkingLevel && onThinkingClick && (
              <button
                type="button"
                onClick={onThinkingClick}
                className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#1c263e] hover:bg-[#4e75ff]/15 text-slate-300 hover:text-[#4e75ff] text-[11px] font-medium border border-white/5 transition-colors"
                title="点击循环切换 Thinking 档位"
              >
                <Brain className="w-3 h-3 text-amber-400" />
                <span>Thinking: {thinkingLevel}</span>
              </button>
            )}

            {/* /plan 快捷按钮 */}
            <button
              type="button"
              onClick={() => setInput('/plan ')}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#1c263e] hover:bg-[#4e75ff]/15 text-slate-400 hover:text-[#4e75ff] text-[11px] font-mono transition-colors border border-transparent hover:border-[#4e75ff]/30"
            >
              <Sparkles className="w-3 h-3 text-[#4e75ff]" />
              <span>/plan</span>
            </button>

            {/* /cost 快捷按钮 */}
            <button
              type="button"
              onClick={() => setInput('/cost')}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#1c263e] hover:bg-[#4e75ff]/15 text-slate-400 hover:text-amber-400 text-[11px] font-mono transition-colors border border-transparent hover:border-amber-500/30"
            >
              <Zap className="w-3 h-3 text-amber-400" />
              <span>/cost</span>
            </button>

            {/* @ 文件引用提示 */}
            <button
              type="button"
              onClick={() => setInput((prev) => prev + '@')}
              className="hidden sm:flex items-center gap-0.5 px-2 py-0.5 rounded-full bg-[#1c263e] text-slate-400 hover:text-slate-200 text-[11px] font-mono transition-colors"
              title="插入文件引用"
            >
              <AtSign className="w-3 h-3" />
              <span>file</span>
            </button>
          </div>

          {/* 清屏图标 */}
          {onClearChat && (
            <button
              type="button"
              onClick={onClearChat}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.06] transition-colors"
              title="清空消息列表"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* 核心多行输入框 */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向 DeepSeek Harness 提问或派发任务，输入 / 触发命令或技能..."
          rows={1}
          disabled={disabled}
          className="w-full bg-transparent px-5 pt-3.5 pb-12 text-sm text-slate-100 placeholder-slate-500 resize-none focus:outline-none min-h-[52px] max-h-[180px] leading-relaxed font-sans"
        />

        {/* 底部右侧发送按钮 */}
        <div className="absolute bottom-3 right-3 flex items-center gap-2">
          {isGenerating ? (
            <button
              onClick={onCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-rose-500/15 text-rose-400 hover:bg-rose-500/25 text-xs font-semibold border border-rose-500/30 transition-all active:scale-95 shadow-sm"
              title="停止生成"
            >
              <Square className="w-3 h-3 fill-current" />
              <span>停止</span>
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 font-mono hidden sm:inline select-none">
                Enter 发送
              </span>
              <button
                onClick={handleSend}
                disabled={!input.trim() || disabled}
                className={`p-2 rounded-full transition-all active:scale-95 ${
                  input.trim() && !disabled
                    ? 'bg-gradient-to-r from-[#4e75ff] to-[#3b82f6] hover:from-[#3d61f5] hover:to-[#2563eb] text-white shadow-lg shadow-blue-500/30 cursor-pointer'
                    : 'bg-white/[0.06] text-slate-500 cursor-not-allowed'
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
