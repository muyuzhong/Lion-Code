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
    <div className="my-2.5 rounded-2xl border border-[#4e75ff]/25 bg-[#141b2d] shadow-sm overflow-hidden transition-all">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3.5 py-2 text-xs text-slate-300 hover:bg-[#4e75ff]/10 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isActive ? (
            <div className="p-1 rounded-lg bg-[#4e75ff]/15 text-[#4e75ff]">
              <Sparkles className="w-3.5 h-3.5 animate-spin text-[#4e75ff]" />
            </div>
          ) : (
            <div className="p-1 rounded-lg bg-white/[0.06] text-slate-400">
              <Brain className="w-3.5 h-3.5" />
            </div>
          )}
          <span className="font-semibold tracking-tight text-slate-100">
            {isActive ? 'Thinking Process (思考中)...' : 'Thought (思考过程)'}
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#4e75ff]/15 text-[#4e75ff]">
            {thinking.length} chars
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-slate-400">
          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </div>
      </button>

      {isOpen && (
        <div className="px-4 pb-3.5 pt-1.5 border-t border-white/[0.08] font-mono text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto bg-[#0b0f19]/60">
          {thinking || '正在思考分析...'}
        </div>
      )}
    </div>
  );
};
