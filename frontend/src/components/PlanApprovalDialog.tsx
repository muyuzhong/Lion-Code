import React from 'react';
import { CheckCircle, Edit3, ListTree, Play, RefreshCw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PlanApprovalRequest } from '../types';

interface PlanApprovalDialogProps {
  request: PlanApprovalRequest;
  onRespond: (requestId: string, choice: string, feedback?: string) => void;
}

export const PlanApprovalDialog: React.FC<PlanApprovalDialogProps> = ({ request, onRespond }) => {
  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-center justify-center p-4 select-none">
      <div className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-3xl border border-white/10 bg-[#161e31]/95 text-slate-100 shadow-2xl overflow-hidden backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-white/10 bg-[#101524]">
          <div className="p-2 rounded-xl bg-[#4e75ff]/15 text-[#4e75ff]">
            <ListTree className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">
              Plan 计划审批确认 (Plan Approval)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              DeepSeek Harness 已生成改造方案，请审阅以下步骤并选择执行策略。
            </p>
          </div>
        </div>

        {/* 计划 Markdown 预览 */}
        <div className="flex-1 p-6 overflow-y-auto prose prose-sm prose-invert max-w-none font-sans text-xs text-slate-200 bg-[#0b0f19]/60">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {request.plan}
          </ReactMarkdown>
        </div>

        {/* 底部 4 选 1 按钮 */}
        <div className="p-4 border-t border-white/10 bg-[#101524] flex flex-wrap items-center justify-end gap-2.5 text-xs">
          <button
            onClick={() => onRespond(request.requestId, 'keep-planning')}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl font-medium text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> 继续规划
          </button>
          <button
            onClick={() => onRespond(request.requestId, 'manual-execute')}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl font-medium text-slate-300 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Edit3 className="w-3.5 h-3.5" /> 我手动执行
          </button>
          <button
            onClick={() => onRespond(request.requestId, 'clear-and-execute')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl font-medium bg-white/10 hover:bg-white/20 text-slate-200 transition-colors"
          >
            <CheckCircle className="w-3.5 h-3.5 text-[#4e75ff]" /> 清空历史并执行
          </button>
          <button
            onClick={() => onRespond(request.requestId, 'execute')}
            className="flex items-center gap-1.5 px-5 py-2 rounded-xl font-medium bg-gradient-to-r from-[#4e75ff] to-[#3b82f6] hover:from-[#3d61f5] hover:to-[#2563eb] text-white shadow-lg shadow-blue-500/25 transition-all active:scale-[0.98]"
          >
            <Play className="w-3.5 h-3.5 fill-current" /> 允许自动执行
          </button>
        </div>
      </div>
    </div>
  );
};
