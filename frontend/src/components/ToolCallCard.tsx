import React, { useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileCode,
  Globe,
  Loader2,
  Search,
  Terminal,
  Wrench,
  XCircle,
} from 'lucide-react';
import { ToolCallItem } from '../types';

interface ToolCallCardProps {
  tool: ToolCallItem;
}

export const ToolCallCard: React.FC<ToolCallCardProps> = ({ tool }) => {
  const [isOpen, setIsOpen] = useState(false);

  const getToolIcon = (name: string) => {
    const lower = name.toLowerCase();
    if (lower.includes('bash') || lower.includes('command') || lower.includes('terminal')) {
      return <Terminal className="w-3.5 h-3.5 text-blue-500" />;
    }
    if (lower.includes('file') || lower.includes('view') || lower.includes('write') || lower.includes('replace')) {
      return <FileCode className="w-3.5 h-3.5 text-amber-500" />;
    }
    if (lower.includes('search') || lower.includes('grep') || lower.includes('find')) {
      return <Search className="w-3.5 h-3.5 text-emerald-500" />;
    }
    if (lower.includes('web') || lower.includes('url')) {
      return <Globe className="w-3.5 h-3.5 text-purple-500" />;
    }
    return <Wrench className="w-3.5 h-3.5 text-neutral-400" />;
  };

  const getStatusBadge = () => {
    if (tool.status === 'running') {
      return (
        <span className="flex items-center gap-1 text-[11px] text-blue-500 dark:text-blue-400 font-medium">
          <Loader2 className="w-3 h-3 animate-spin" /> 执行中
        </span>
      );
    }
    if (tool.status === 'error') {
      return (
        <span className="flex items-center gap-1 text-[11px] text-red-500 dark:text-red-400 font-medium">
          <XCircle className="w-3 h-3" /> 失败
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
        <CheckCircle2 className="w-3 h-3" /> 完成
      </span>
    );
  };

  const renderParameters = () => {
    if (!tool.parameters) return null;
    if (typeof tool.parameters === 'string') return tool.parameters;
    // 如果是 run_command，直接显示 CommandLine
    if (tool.parameters.CommandLine) {
      return `$ ${tool.parameters.CommandLine}`;
    }
    // 如果是 TargetFile / AbsolutePath
    if (tool.parameters.TargetFile || tool.parameters.AbsolutePath) {
      return `${tool.parameters.TargetFile || tool.parameters.AbsolutePath}`;
    }
    return JSON.stringify(tool.parameters, null, 2);
  };

  return (
    <div className="my-2 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900/70 shadow-sm overflow-hidden transition-all">
      {/* 头部栏 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-neutral-50 dark:hover:bg-neutral-800/40 text-left transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1 rounded bg-neutral-100 dark:bg-neutral-800 flex-shrink-0">
            {getToolIcon(tool.toolName)}
          </div>
          <span className="font-mono text-xs font-semibold text-neutral-800 dark:text-neutral-200 truncate">
            {tool.toolName}
          </span>
          <span className="text-xs text-neutral-400 font-mono truncate max-w-[200px] sm:max-w-xs opacity-80">
            {typeof tool.parameters === 'object' && tool.parameters?.CommandLine
              ? tool.parameters.CommandLine
              : typeof tool.parameters === 'object' && (tool.parameters?.TargetFile || tool.parameters?.AbsolutePath)
              ? (tool.parameters.TargetFile || tool.parameters.AbsolutePath).split(/[\\/]/).pop()
              : ''}
          </span>
        </div>

        <div className="flex items-center gap-2.5 flex-shrink-0">
          {getStatusBadge()}
          {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-neutral-400" /> : <ChevronRight className="w-3.5 h-3.5 text-neutral-400" />}
        </div>
      </button>

      {/* 折叠内容 */}
      {isOpen && (
        <div className="px-3 pb-3 pt-1 border-t border-neutral-100 dark:border-neutral-800/60 space-y-2 text-xs">
          {/* 参数 */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400 mb-1">输入参数</div>
            <pre className="p-2 rounded bg-neutral-100 dark:bg-neutral-950/80 font-mono text-[11px] text-neutral-700 dark:text-neutral-300 overflow-x-auto whitespace-pre-wrap">
              {renderParameters()}
            </pre>
          </div>

          {/* 输出结果 */}
          {tool.result && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400 mb-1">执行结果</div>
              <pre
                className={`p-2 rounded font-mono text-[11px] overflow-x-auto whitespace-pre-wrap max-h-56 ${
                  tool.isError
                    ? 'bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900/40'
                    : 'bg-neutral-100 dark:bg-neutral-950/80 text-neutral-700 dark:text-neutral-300'
                }`}
              >
                {tool.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
