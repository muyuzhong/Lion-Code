import React, { useState } from "react";
import { Check, X, ShieldAlert, Sparkles, Play, Wrench, RefreshCw } from "lucide-react";
import { ConfirmRequest, PlanApprovalRequest } from "@/types/chat";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ConfirmBannerProps {
  request: ConfirmRequest | null;
  onRespond: (requestId: string, approved: boolean) => void;
}

export function ConfirmBanner({ request, onRespond }: ConfirmBannerProps) {
  if (!request) return null;

  return (
    <div className="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 w-full max-w-xl px-4 animate-in fade-in slide-in-from-bottom-4">
      <div className="rounded-xl border border-amber-500/50 bg-zinc-900 p-4 shadow-2xl text-zinc-100">
        <div className="flex items-start gap-3">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400">
            <ShieldAlert className="size-4" />
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
              操作权限确认 (Confirmation Required)
            </h4>
            <p className="mt-1 text-xs text-zinc-200 whitespace-pre-wrap font-mono">
              {request.message}
            </p>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-end gap-2 border-t border-zinc-800 pt-3">
          <button
            type="button"
            onClick={() => onRespond(request.requestId, false)}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 transition"
          >
            <X className="size-3.5" />
            <span>拒绝 (Deny)</span>
          </button>
          <button
            type="button"
            onClick={() => onRespond(request.requestId, true)}
            className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-3.5 py-1.5 text-xs font-medium text-black hover:bg-amber-400 transition shadow-xs"
          >
            <Check className="size-3.5" />
            <span>允许执行 (Approve)</span>
          </button>
        </div>
      </div>
    </div>
  );
}

interface PlanApprovalModalProps {
  request: PlanApprovalRequest | null;
  onRespond: (
    requestId: string,
    choice: "clear-and-execute" | "execute" | "manual-execute" | "keep-planning",
    feedback?: string
  ) => void;
}

export function PlanApprovalModal({ request, onRespond }: PlanApprovalModalProps) {
  const [feedback, setFeedback] = useState("");

  if (!request) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md animate-in fade-in">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-zinc-800 bg-zinc-900 shadow-2xl text-zinc-100">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-7 items-center justify-center rounded-lg bg-zinc-800 text-zinc-100">
              <Sparkles className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">Plan 模式方案审批</h3>
              <p className="text-xs text-zinc-400">Lion Code 已完成方案规划，请选择接下来的执行方式</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="prose prose-sm dark:prose-invert max-w-none rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{request.plan}</ReactMarkdown>
          </div>

          <div>
            <label className="text-xs font-medium text-zinc-300">反馈或补充指示 (可选)</label>
            <input
              type="text"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="如有修改建议，可在此输入..."
              className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-hidden focus:ring-1 focus:ring-zinc-500"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 border-t border-zinc-800 bg-zinc-950/50 p-4">
          <button
            type="button"
            onClick={() => onRespond(request.requestId, "clear-and-execute", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl bg-zinc-100 px-3 py-2.5 text-center text-zinc-950 transition hover:bg-zinc-200 shadow-xs"
          >
            <Play className="size-4" />
            <span className="text-xs font-semibold">清空并执行</span>
            <span className="text-[10px] opacity-75">全新上下文执行</span>
          </button>

          <button
            type="button"
            onClick={() => onRespond(request.requestId, "execute", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-center transition hover:bg-zinc-800 text-zinc-200"
          >
            <Play className="size-4 text-emerald-400" />
            <span className="text-xs font-semibold">继续并执行</span>
            <span className="text-[10px] text-zinc-400">保留对话历史</span>
          </button>

          <button
            type="button"
            onClick={() => onRespond(request.requestId, "manual-execute", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-center transition hover:bg-zinc-800 text-zinc-200"
          >
            <Wrench className="size-4 text-blue-400" />
            <span className="text-xs font-semibold">手动执行</span>
            <span className="text-[10px] text-zinc-400">逐条指令手动确认</span>
          </button>

          <button
            type="button"
            onClick={() => onRespond(request.requestId, "keep-planning", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-center transition hover:bg-zinc-800 text-zinc-200"
          >
            <RefreshCw className="size-4 text-amber-400" />
            <span className="text-xs font-semibold">继续规划</span>
            <span className="text-[10px] text-zinc-400">留在 Plan 模式补充</span>
          </button>
        </div>
      </div>
    </div>
  );
}
