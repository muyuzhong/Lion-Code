import React, { useEffect } from 'react';
import { Check, ShieldAlert, X } from 'lucide-react';
import { ConfirmRequest } from '../types';

interface ConfirmBannerProps {
  request: ConfirmRequest;
  onRespond: (requestId: string, approved: boolean) => void;
}

export const ConfirmBanner: React.FC<ConfirmBannerProps> = ({ request, onRespond }) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        onRespond(request.requestId, true);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onRespond(request.requestId, false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [request.requestId, onRespond]);

  return (
    <div className="fixed bottom-28 left-1/2 -translate-x-1/2 z-50 w-full max-w-xl px-4 animate-in fade-in slide-in-from-bottom-5 duration-200 select-none">
      <div className="rounded-2xl border border-amber-500/40 bg-neutral-900/90 text-white p-4 shadow-2xl shadow-amber-500/10 backdrop-blur-2xl">
        <div className="flex items-start gap-3.5">
          <div className="p-2.5 rounded-xl bg-amber-500/10 text-amber-400 flex-shrink-0 mt-0.5 border border-amber-500/20">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-semibold text-neutral-100">
                敏感操作权限确认
              </h4>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-medium">
                HIGH RISK
              </span>
            </div>
            <p className="text-xs text-neutral-300 mt-2 font-mono break-all bg-black/50 p-2.5 rounded-xl border border-white/10">
              {request.message}
            </p>
            <div className="flex items-center justify-end gap-2.5 mt-3.5">
              <button
                onClick={() => onRespond(request.requestId, false)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-medium text-neutral-300 hover:bg-white/10 transition-colors"
              >
                <X className="w-3.5 h-3.5" /> 拒绝 (Esc)
              </button>
              <button
                onClick={() => onRespond(request.requestId, true)}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-xs font-medium bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-white shadow-lg shadow-amber-500/25 transition-all"
              >
                <Check className="w-3.5 h-3.5" /> 允许执行 (Enter)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
