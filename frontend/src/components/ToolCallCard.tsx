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
      return <Terminal className="w-3.5 h-3.5 text-blue-400" />;
    }
    if (lower.includes('file') || lower.includes('view') || lower.includes('write') || lower.includes('replace')) {
      return <FileCode className="w-3.5 h-3.5 text-amber-400" />;
    }
    if (lower.includes('search') || lower.includes('grep') || lower.includes('find')) {
      return <Search className="w-3.5 h-3.5 text-emerald-400" />;
    }
    if (lower.includes('web') || lower.includes('url')) {
      return <Globe className="w-3.5 h-3.5 text-purple-400" />;
    }
    return <Wrench className="w-3.5 h-3.5 text-neutral-400" />;
  };

  const getStatusPill = () => {
    if (tool.status === 'running') {
      return (
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-500 text-[10px] font-medium animate-pulse border border-blue-500/20">
          <Loader2 className="w-3 h-3 animate-spin" /> 执行中
        </span>
      );
    }
    if (tool.status === 'error') {
      return (
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-500 text-[10px] font-medium border border-rose-500/20">
          <XCircle className="w-3 h-3" /> 失败
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 text-[10px] font-medium border border-emerald-500/20">
        <CheckCircle2 className="w-3 h-3" /> 完成
      </span>
    );
  };

  const renderParameters = () => {
    if (!tool.parameters) return null;
    if (typeof tool.parameters === 'string') return tool.parameters;
    if (tool.parameters.CommandLine) {
      return `$ ${tool.parameters.CommandLine}`;
    }
    if (tool.parameters.TargetFile || tool.parameters.AbsolutePath) {
      return `${tool.parameters.TargetFile || tool.parameters.AbsolutePath}`;
    }
    return JSON.stringify(tool.parameters, null, 2);
  };

  return (
    <div className="my-2.5 rounded-2xl border border-neutral-200/80 dark:border-neutral-800 bg-white/60 dark:bg-neutral-900/50 backdrop-blur-md shadow-sm overflow-hidden lobe-card-hover transition-all">
      {/* 头部：macOS 风格圆点 + 工具名 + 状态 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-neutral-100/50 dark:hover:bg-white/[0.03] text-left transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          {/* macOS 风格 3 色小圆点 */}
          <div className="flex items-center gap-1.5 pr-1">
            <span className="w-2.5 h-2.5 rounded-full bg-red-400/80" />
            <span className="w-2.5 h-2.5 rounded-full bg-amber-400/80" />
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400/80" />
          </div>

          <div className="flex items-center gap-1.5 truncate">
            {getToolIcon(tool.toolName)}
            <span className="font-mono text-xs font-semibold text-neutral-800 dark:text-neutral-200">
              {tool.toolName}
            </span>
            <span className="text-[11px] text-neutral-400 font-mono truncate max-w-[240px] opacity-70">
              {typeof tool.parameters === 'object' && tool.parameters?.CommandLine
                ? tool.parameters.CommandLine
                : typeof tool.parameters === 'object' && (tool.parameters?.TargetFile || tool.parameters?.AbsolutePath)
                ? (tool.parameters.TargetFile || tool.parameters.AbsolutePath).split(/[\\/]/).pop()
                : ''}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {getStatusPill()}
          {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-neutral-400" /> : <ChevronRight className="w-3.5 h-3.5 text-neutral-400" />}
        </div>
      </button>

      {/* 折叠内容 */}
      {isOpen && (
        <div className="px-3.5 pb-3.5 pt-1.5 border-t border-neutral-200/60 dark:border-neutral-800/80 space-y-2.5 text-xs bg-neutral-950/20">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400 mb-1">执行输入 (Input)</div>
            <pre className="p-2.5 rounded-xl bg-neutral-100 dark:bg-neutral-950/80 font-mono text-[11px] text-neutral-700 dark:text-neutral-300 overflow-x-auto whitespace-pre-wrap border border-neutral-200/60 dark:border-neutral-800/50">
              {renderParameters()}
            </pre>
          </div>

          {tool.result && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400 mb-1">输出结果 (Output)</div>
              <pre
                className={`p-2.5 rounded-xl font-mono text-[11px] overflow-x-auto whitespace-pre-wrap max-h-60 border ${
                  tool.isError
                    ? 'bg-rose-950/30 text-rose-300 border-rose-900/50'
                    : 'bg-neutral-100 dark:bg-neutral-950/80 text-neutral-700 dark:text-neutral-300 border-neutral-200/60 dark:border-neutral-800/50'
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
