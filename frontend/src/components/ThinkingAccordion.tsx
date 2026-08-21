import React, { useState } from 'react';
import { Brain, ChevronDown, ChevronRight, Sparkles } from 'lucide-react';

interface ThinkingAccordionProps {
  thinking: string;
  isActive?: boolean;
}

export const ThinkingAccordion: React.FC<ThinkingAccordionProps> = ({ thinking, isActive }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!thinking && !isActive) return null;

  return (
    <div className="my-2.5 rounded-lg border border-neutral-200/60 dark:border-neutral-800 bg-neutral-50/50 dark:bg-neutral-900/40 text-xs transition-all">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-2 text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-200 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isActive ? (
            <Sparkles className="w-3.5 h-3.5 text-amber-500 animate-pulse" />
          ) : (
            <Brain className="w-3.5 h-3.5 text-neutral-400" />
          )}
          <span className="font-medium">
            {isActive ? '正在思考中...' : '思考过程 (Thinking Process)'}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-neutral-400">
          <span className="text-[10px] font-mono opacity-70">
            {thinking.length > 0 ? `${thinking.length} 字符` : ''}
          </span>
          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </div>
      </button>

      {isOpen && (
        <div className="px-3 pb-3 pt-1 border-t border-neutral-200/50 dark:border-neutral-800/80 font-mono text-[11px] text-neutral-600 dark:text-neutral-400 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">
          {thinking || '思考中...'}
        </div>
      )}
    </div>
  );
};
