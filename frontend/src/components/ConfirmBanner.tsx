import React, { useEffect } from 'react';
import { AlertTriangle, Check, X } from 'lucide-react';
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
    <div className="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 w-full max-w-xl px-4 animate-in fade-in slide-in-from-bottom-4 duration-200">
      <div className="rounded-xl border border-amber-500/40 bg-white/95 dark:bg-neutral-900/95 p-4 shadow-xl backdrop-blur-md">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg bg-amber-500/10 text-amber-500 flex-shrink-0 mt-0.5">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              敏感操作确认 (Permission Required)
            </h4>
            <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1 font-mono break-all bg-neutral-100 dark:bg-neutral-950 p-2 rounded border border-neutral-200 dark:border-neutral-800">
              {request.message}
            </p>
            <div className="flex items-center justify-end gap-2.5 mt-3.5">
              <button
                onClick={() => onRespond(request.requestId, false)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
              >
                <X className="w-3.5 h-3.5" /> 拒绝 (Esc)
              </button>
              <button
                onClick={() => onRespond(request.requestId, true)}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-amber-500 hover:bg-amber-600 text-white shadow-sm transition-all"
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
