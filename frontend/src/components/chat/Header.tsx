import React from "react";
import { PanelLeft, Plus, Settings, Sun, Moon } from "lucide-react";
import { ModelChoice, ServerStatus } from "@/types/chat";
import { ModelSelectorDropdown } from "./ModelSelectorDropdown";
import { useTheme } from "@/context/ThemeContext";

interface HeaderProps {
  onToggleSidebar: () => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
  status: ServerStatus | null;
  models: ModelChoice[];
  onModelChanged: () => void;
  isConnected: boolean;
}

export function Header({
  onToggleSidebar,
  onNewChat,
  onOpenSettings,
  status,
  models,
  onModelChanged,
  isConnected,
}: HeaderProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="flex h-13 shrink-0 items-center justify-between border-b border-zinc-200 dark:border-zinc-800/80 bg-white/80 dark:bg-zinc-950/80 px-4 backdrop-blur-md transition-colors">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="flex size-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100 transition"
          title="切换侧边栏"
        >
          <PanelLeft className="size-4" />
        </button>

        <button
          type="button"
          onClick={onNewChat}
          className="flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-800 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/90 transition shadow-2xs"
        >
          <Plus className="size-3.5" />
          <span>新会话</span>
        </button>

        {/* Quick Model Selector Dropdown */}
        <ModelSelectorDropdown
          status={status}
          models={models}
          onModelChanged={onModelChanged}
        />
      </div>

      <div className="flex items-center gap-2.5">
        {/* Connection status */}
        <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 dark:text-zinc-400">
          <span
            className={`size-2 rounded-full ${
              isConnected
                ? "bg-emerald-500 shadow-xs shadow-emerald-500/50"
                : "bg-rose-500 animate-pulse"
            }`}
          />
          <span className="hidden sm:inline font-mono">{isConnected ? "Online" : "Connecting..."}</span>
        </div>

        {/* 权限模式徽标：值来自 status.permission_mode（default/acceptEdits/bypassPermissions/dontAsk），纯展示 */}
        {status?.permission_mode && (
          <div
            className="hidden md:flex text-[11px] font-mono text-zinc-500 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-900/60 px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-800"
            title="权限模式 (permission_mode)"
          >
            {status.permission_mode}
          </div>
        )}

        {/* Workspace directory */}
        {status?.cwd && (
          <div className="hidden md:flex max-w-[180px] truncate text-[11px] font-mono text-zinc-500 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-900/60 px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-800">
            {status.cwd.split(/[/\\]/).pop()}
          </div>
        )}

        {/* Theme Toggle Button */}
        <button
          type="button"
          onClick={toggleTheme}
          className="flex size-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100 transition"
          title={theme === "dark" ? "切换为浅色模式" : "切换为深色模式"}
        >
          {theme === "dark" ? <Sun className="size-4 text-amber-400" /> : <Moon className="size-4 text-zinc-700" />}
        </button>

        {/* Single Settings Button */}
        <button
          type="button"
          onClick={onOpenSettings}
          className="flex size-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100 transition"
          title="API 与模型配置"
        >
          <Settings className="size-4" />
        </button>
      </div>
    </header>
  );
}
