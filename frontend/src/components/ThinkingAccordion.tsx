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
    <div className="my-2.5 rounded-2xl border border-purple-500/20 bg-purple-500/[0.03] dark:bg-purple-950/20 shadow-sm overflow-hidden transition-all">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3.5 py-2 text-xs text-neutral-600 dark:text-neutral-300 hover:bg-purple-500/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isActive ? (
            <div className="p-1 rounded-lg bg-purple-500/10 text-purple-500">
              <Sparkles className="w-3.5 h-3.5 animate-spin text-purple-500" />
            </div>
          ) : (
            <div className="p-1 rounded-lg bg-neutral-200 dark:bg-neutral-800 text-neutral-500">
              <Brain className="w-3.5 h-3.5" />
            </div>
          )}
          <span className="font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
            {isActive ? '深度思考中 (Thinking)...' : '思考过程 (Reasoning)'}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-purple-500/10 text-purple-600 dark:text-purple-400">
            {thinking.length} 字符
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-neutral-400">
          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </div>
      </button>

      {isOpen && (
        <div className="px-4 pb-3.5 pt-1.5 border-t border-purple-500/10 font-mono text-[11px] text-neutral-600 dark:text-neutral-300 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto bg-neutral-950/20">
          {thinking || '思考中...'}
        </div>
      )}
    </div>
  );
};
