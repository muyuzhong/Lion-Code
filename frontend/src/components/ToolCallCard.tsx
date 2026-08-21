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
      return <Terminal className="w-3.5 h-3.5 text-[#4e75ff]" />;
    }
    if (lower.includes('file') || lower.includes('view') || lower.includes('write') || lower.includes('replace')) {
      return <FileCode className="w-3.5 h-3.5 text-amber-400" />;
    }
    if (lower.includes('search') || lower.includes('grep') || lower.includes('find')) {
      return <Search className="w-3.5 h-3.5 text-emerald-400" />;
    }
    if (lower.includes('web') || lower.includes('url')) {
      return <Globe className="w-3.5 h-3.5 text-sky-400" />;
    }
    return <Wrench className="w-3.5 h-3.5 text-slate-400" />;
  };

  const getStatusPill = () => {
    if (tool.status === 'running') {
      return (
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#4e75ff]/15 text-[#4e75ff] text-[10px] font-medium animate-pulse border border-[#4e75ff]/30">
          <Loader2 className="w-3 h-3 animate-spin" /> 执行中
        </span>
      );
    }
    if (tool.status === 'error') {
      return (
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-400 text-[10px] font-medium border border-rose-500/30">
          <XCircle className="w-3 h-3" /> 失败
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 text-[10px] font-medium border border-emerald-500/30">
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
    <div className="my-2.5 rounded-2xl border border-white/[0.08] bg-[#141b2d]/80 backdrop-blur-md shadow-sm overflow-hidden dsh-card-hover transition-all">
      {/* 头部：DSH 风格工具状态栏 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-white/[0.03] text-left transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-1 rounded-lg bg-white/[0.06] text-slate-300">
            {getToolIcon(tool.toolName)}
          </div>

          <div className="flex items-center gap-2 truncate">
            <span className="font-mono text-xs font-semibold text-slate-200">
              {tool.toolName}
            </span>
            <span className="text-[11px] text-slate-400 font-mono truncate max-w-[240px] opacity-80">
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
          {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
        </div>
      </button>

      {/* 折叠内容 */}
      {isOpen && (
        <div className="px-3.5 pb-3.5 pt-1.5 border-t border-white/[0.08] space-y-2.5 text-xs bg-[#0b0f19]/70">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">执行入参 (Input)</div>
            <pre className="p-2.5 rounded-xl bg-[#121824] font-mono text-[11px] text-slate-300 overflow-x-auto whitespace-pre-wrap border border-white/[0.08]">
              {renderParameters()}
            </pre>
          </div>

          {tool.result && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">控制台输出 (Output)</div>
              <pre
                className={`p-2.5 rounded-xl font-mono text-[11px] overflow-x-auto whitespace-pre-wrap max-h-60 border ${
                  tool.isError
                    ? 'bg-rose-950/30 text-rose-300 border-rose-900/50'
                    : 'bg-[#121824] text-slate-300 border-white/[0.08]'
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
