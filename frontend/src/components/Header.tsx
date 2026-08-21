import React, { useState } from 'react';
import {
  Activity,
  Bot,
  Brain,
  ChevronDown,
  Cpu,
  Trash2,
} from 'lucide-react';
import { ModelChoice, ServerStatus } from '../types';

interface HeaderProps {
  status: ServerStatus | null;
  models: ModelChoice[];
  isConnected: boolean;
  onModelSelect: (model: string) => void;
  onThinkingChange: (level: string) => void;
  onClearChat: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  status,
  models,
  isConnected,
  onModelSelect,
  onThinkingChange,
  onClearChat,
}) => {
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);

  return (
    <header className="h-14 border-b border-neutral-200/80 dark:border-neutral-800/80 bg-white/70 dark:bg-neutral-950/70 backdrop-blur-xl px-4 flex items-center justify-between z-10 sticky top-0 select-none">
      {/* 左侧：模型选择 Pill (LobeChat 标志性组件) */}
      <div className="flex items-center gap-3">
        <div className="relative">
          <button
            onClick={() => setIsModelDropdownOpen(!isModelDropdownOpen)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-neutral-200 dark:border-white/10 bg-white/80 dark:bg-white/[0.05] hover:bg-neutral-100 dark:hover:bg-white/[0.08] shadow-sm transition-all text-xs"
          >
            <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-purple-500 to-indigo-500 flex items-center justify-center text-white flex-shrink-0">
              <Bot className="w-3 h-3" />
            </div>
            <span className="font-semibold text-neutral-900 dark:text-neutral-100 max-w-[160px] truncate">
              {status?.model || 'gpt-4o'}
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-purple-500/10 text-purple-600 dark:text-purple-400 font-medium">
              {status?.providerName || 'openai'}
            </span>
            <ChevronDown className="w-3 h-3 text-neutral-400" />
          </button>

          {/* 模型下拉菜单 */}
          {isModelDropdownOpen && (
            <div className="absolute top-full left-0 mt-1.5 w-60 rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 shadow-2xl p-1.5 z-50 animate-in fade-in zoom-in-95 duration-150">
              <div className="px-2.5 py-1.5 text-[10px] font-semibold text-neutral-400 uppercase tracking-wider">
                选择模型 (Model Choices)
              </div>
              <div className="max-h-60 overflow-y-auto space-y-0.5">
                {models.map((m) => {
                  const isCurrent = m.model === status?.model;
                  return (
                    <button
                      key={m.model}
                      onClick={() => {
                        onModelSelect(m.model);
                        setIsModelDropdownOpen(false);
                      }}
                      className={`w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-xs text-left transition-colors ${
                        isCurrent
                          ? 'bg-purple-500/10 text-purple-600 dark:text-purple-400 font-semibold'
                          : 'text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800'
                      }`}
                    >
                      <div className="flex items-center gap-2 truncate">
                        <Cpu className="w-3.5 h-3.5 text-neutral-400" />
                        <span className="truncate">{m.model}</span>
                      </div>
                      <span className="text-[10px] text-neutral-400 uppercase font-mono">
                        {m.provider_name}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 右侧：Thinking 档位、Token 用量、连接状态、清空按钮 */}
      <div className="flex items-center gap-2.5">
        {/* Thinking 模式调节 */}
        {status?.availableThinkingLevels && status.availableThinkingLevels.length > 0 && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-neutral-200 dark:border-white/10 bg-white/80 dark:bg-white/[0.04] text-xs">
            <Brain className="w-3.5 h-3.5 text-amber-500 animate-pulse" />
            <select
              value={status.thinkingLevel}
              onChange={(e) => onThinkingChange(e.target.value)}
              className="bg-transparent text-xs text-neutral-700 dark:text-neutral-300 focus:outline-none cursor-pointer font-medium"
            >
              {status.availableThinkingLevels.map((lvl) => (
                <option key={lvl} value={lvl} className="bg-white dark:bg-neutral-900">
                  Thinking: {lvl}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Token 统计 Pill */}
        {status && (
          <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-neutral-200/80 dark:border-white/10 bg-neutral-50/50 dark:bg-white/[0.02] text-[11px] font-mono text-neutral-500">
            <Activity className="w-3 h-3 text-purple-400" />
            <span>{status.inputTokens} / {status.outputTokens} tkn</span>
          </div>
        )}

        {/* 状态连接圆点 */}
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-neutral-100/80 dark:bg-white/[0.04] text-[11px] font-medium">
          <span
            className={`w-2 h-2 rounded-full ${
              isConnected
                ? 'bg-emerald-500 shadow-sm shadow-emerald-500/80'
                : 'bg-rose-500 animate-ping'
            }`}
          />
          <span className="hidden sm:inline text-neutral-400">
            {isConnected ? '在线' : '断开'}
          </span>
        </div>

        {/* 清屏图标 */}
        <button
          onClick={onClearChat}
          className="p-2 rounded-xl text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
          title="清空当前消息窗口"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
