import React, { useState } from "react";
import { AlertTriangle, Check, X, ShieldAlert, Sparkles, Play, Wrench, RefreshCw } from "lucide-react";
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
      <div className="rounded-xl border border-amber-500/40 bg-zinc-900/95 p-4 shadow-2xl backdrop-blur-md text-foreground">
        <div className="flex items-start gap-3">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400">
            <ShieldAlert className="size-4" />
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
              操作权限确认 (Confirmation Required)
            </h4>
            <p className="mt-1 text-xs text-zinc-300 whitespace-pre-wrap font-mono">
              {request.message}
            </p>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-end gap-2 border-t border-border/40 pt-3">
          <button
            type="button"
            onClick={() => onRespond(request.request_id, false)}
            className="flex items-center gap-1.5 rounded-lg border border-border/80 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition"
          >
            <X className="size-3.5" />
            <span>拒绝 (Deny)</span>
          </button>
          <button
            type="button"
            onClick={() => onRespond(request.request_id, true)}
            className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-3.5 py-1.5 text-xs font-medium text-black hover:bg-amber-400 transition"
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs animate-in fade-in">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-border bg-card shadow-2xl text-card-foreground">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/60 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Sparkles className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">Plan 模式方案审批</h3>
              <p className="text-xs text-muted-foreground">Lion Code 已完成方案规划，请选择接下来的执行方式</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="prose prose-sm dark:prose-invert max-w-none rounded-xl border border-border/60 bg-muted/20 p-4 text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{request.plan}</ReactMarkdown>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground">反馈或补充指示 (可选)</label>
            <input
              type="text"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="如有修改建议，可在此输入..."
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-xs focus:outline-hidden focus:ring-1 focus:ring-primary"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 border-t border-border/60 bg-muted/10 p-4">
          <button
            type="button"
            onClick={() => onRespond(request.request_id, "clear-and-execute", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl bg-primary px-3 py-2.5 text-center text-primary-foreground transition hover:opacity-90 shadow-xs"
          >
            <Play className="size-4" />
            <span className="text-xs font-semibold">清空并执行</span>
            <span className="text-[10px] opacity-75">全新上下文执行</span>
          </button>

          <button
            type="button"
            onClick={() => onRespond(request.request_id, "execute", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card px-3 py-2.5 text-center transition hover:bg-muted"
          >
            <Play className="size-4 text-emerald-500" />
            <span className="text-xs font-semibold">继续并执行</span>
            <span className="text-[10px] text-muted-foreground">保留对话历史</span>
          </button>

          <button
            type="button"
            onClick={() => onRespond(request.request_id, "manual-execute", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card px-3 py-2.5 text-center transition hover:bg-muted"
          >
            <Wrench className="size-4 text-blue-500" />
            <span className="text-xs font-semibold">手动执行</span>
            <span className="text-[10px] text-muted-foreground">逐条指令手动确认</span>
          </button>

          <button
            type="button"
            onClick={() => onRespond(request.request_id, "keep-planning", feedback)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card px-3 py-2.5 text-center transition hover:bg-muted"
          >
            <RefreshCw className="size-4 text-amber-500" />
            <span className="text-xs font-semibold">继续规划</span>
            <span className="text-[10px] text-muted-foreground">留在 Plan 模式补充</span>
          </button>
        </div>
      </div>
    </div>
  );
}
