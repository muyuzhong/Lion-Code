import React from 'react';
import {
  Activity,
  Brain,
  Menu,
  Moon,
  Settings,
  Sun,
} from 'lucide-react';
import { ServerStatus } from '../types';

interface HeaderProps {
  status: ServerStatus | null;
  isConnected: boolean;
  onOpenSettings: () => void;
  onToggleSidebar: () => void;
  onThinkingChange: (level: string) => void;
  isDark: boolean;
  onToggleTheme: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  status,
  isConnected,
  onOpenSettings,
  onToggleSidebar,
  onThinkingChange,
  isDark,
  onToggleTheme,
}) => {
  return (
    <header className="h-14 border-b border-neutral-200 dark:border-neutral-800/80 bg-white/80 dark:bg-neutral-950/80 backdrop-blur-md px-4 flex items-center justify-between z-10 sticky top-0">
      {/* 左侧：菜单与标题 */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="p-1.5 rounded-lg text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
          title="切换侧边栏"
        >
          <Menu className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm tracking-tight text-neutral-900 dark:text-neutral-100 flex items-center gap-1.5">
            <span className="text-base">🦁</span> Lion Code
          </span>
          <span className="hidden sm:inline-block text-[11px] font-mono px-2 py-0.5 rounded-full bg-neutral-100 dark:bg-neutral-800 text-neutral-500">
            {status?.model || 'gpt-4o'}
          </span>
        </div>
      </div>

      {/* 右侧：状态、Thinking、用量、设置 */}
      <div className="flex items-center gap-3">
        {/* Thinking 切换 */}
        {status?.availableThinkingLevels && status.availableThinkingLevels.length > 0 && (
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-neutral-500">
            <Brain className="w-3.5 h-3.5 text-neutral-400" />
            <select
              value={status.thinkingLevel}
              onChange={(e) => onThinkingChange(e.target.value)}
              className="bg-transparent border border-neutral-200 dark:border-neutral-800 rounded-md px-2 py-1 text-xs text-neutral-700 dark:text-neutral-300 focus:outline-none focus:ring-1 focus:ring-neutral-400 cursor-pointer"
            >
              {status.availableThinkingLevels.map((lvl) => (
                <option key={lvl} value={lvl} className="bg-white dark:bg-neutral-900">
                  Thinking: {lvl}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Token 用量 */}
        {status && (
          <div className="hidden md:flex items-center gap-1.5 text-[11px] font-mono text-neutral-400 px-2 py-1 rounded bg-neutral-50 dark:bg-neutral-900 border border-neutral-200/50 dark:border-neutral-800/50">
            <Activity className="w-3 h-3 text-neutral-400" />
            <span>{status.inputTokens} in / {status.outputTokens} out</span>
          </div>
        )}

        {/* 连接指示灯 */}
        <div className="flex items-center gap-1.5 text-[11px] font-medium" title={isConnected ? 'WebSocket 已就绪' : '正在连接后端...'}>
          <span
            className={`w-2 h-2 rounded-full ${
              isConnected ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-red-500 animate-ping'
            }`}
          />
          <span className="hidden lg:inline text-neutral-400">
            {isConnected ? '在线' : '离线'}
          </span>
        </div>

        {/* 主题切换 */}
        <button
          onClick={onToggleTheme}
          className="p-1.5 rounded-lg text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
          title="切换深色/浅色模式"
        >
          {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>

        {/* 设置按钮 */}
        <button
          onClick={onOpenSettings}
          className="p-1.5 rounded-lg text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
          title="配置 Provider 与 API Key"
        >
          <Settings className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
