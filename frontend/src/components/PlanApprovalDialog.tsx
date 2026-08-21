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
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-neutral-200 dark:border-neutral-800 bg-neutral-50/50 dark:bg-neutral-900/50">
          <ListTree className="w-5 h-5 text-blue-500" />
          <div>
            <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              Plan 计划审批确认
            </h3>
            <p className="text-xs text-neutral-500">
              Agent 已完成方案规划，请审阅以下执行计划并选择执行方式。
            </p>
          </div>
        </div>

        {/* 计划 Markdown 预览 */}
        <div className="flex-1 p-5 overflow-y-auto prose prose-sm dark:prose-invert max-w-none font-sans text-xs">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {request.plan}
          </ReactMarkdown>
        </div>

        {/* 底部 4 选 1 按钮 */}
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 bg-neutral-50/50 dark:bg-neutral-900/50 flex flex-wrap items-center justify-end gap-2 text-xs">
          <button
            onClick={() => onRespond(request.requestId, 'keep-planning')}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> 继续规划 (Keep Planning)
          </button>
          <button
            onClick={() => onRespond(request.requestId, 'manual-execute')}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors"
          >
            <Edit3 className="w-3.5 h-3.5" /> 我手动执行
          </button>
          <button
            onClick={() => onRespond(request.requestId, 'clear-and-execute')}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg font-medium bg-neutral-200 dark:bg-neutral-800 hover:bg-neutral-300 dark:hover:bg-neutral-700 text-neutral-900 dark:text-neutral-100 transition-colors"
          >
            <CheckCircle className="w-3.5 h-3.5 text-blue-500" /> 清空历史并执行
          </button>
          <button
            onClick={() => onRespond(request.requestId, 'execute')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg font-medium bg-blue-600 hover:bg-blue-700 text-white shadow-sm transition-all"
          >
            <Play className="w-3.5 h-3.5 fill-current" /> 直接自动执行
          </button>
        </div>
      </div>
    </div>
  );
};
