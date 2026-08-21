import React from "react";
import { PanelLeft, Sparkles, Plus, Settings, ChevronDown } from "lucide-react";
import { ServerStatus } from "@/types/chat";

interface HeaderProps {
  onToggleSidebar: () => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
  status: ServerStatus | null;
  isConnected: boolean;
}

export function Header({ onToggleSidebar, onNewChat, onOpenSettings, status, isConnected }: HeaderProps) {
  return (
    <header className="flex h-13 items-center justify-between border-b border-border/40 bg-background/80 px-4 backdrop-blur-md">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition"
          title="切换侧边栏"
        >
          <PanelLeft className="size-4" />
        </button>

        <button
          type="button"
          onClick={onNewChat}
          className="flex items-center gap-1.5 rounded-lg border border-border/80 bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted transition shadow-2xs"
        >
          <Plus className="size-3.5" />
          <span>新会话</span>
        </button>

        {/* Model dropdown / badge */}
        <button
          type="button"
          onClick={onOpenSettings}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold text-foreground hover:bg-muted transition"
        >
          <Sparkles className="size-3.5 text-primary" />
          <span>{status?.model || "Lion Code"}</span>
          <ChevronDown className="size-3 text-muted-foreground" />
        </button>
      </div>

      <div className="flex items-center gap-3">
        {/* Connection status */}
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className={`size-2 rounded-full ${isConnected ? "bg-emerald-500 shadow-xs shadow-emerald-500/50" : "bg-rose-500 animate-pulse"}`} />
          <span className="hidden sm:inline">{isConnected ? "已连接" : "连接中..."}</span>
        </div>

        {/* Workspace directory */}
        {status?.cwd && (
          <div className="hidden md:flex max-w-[200px] truncate text-[11px] font-mono text-muted-foreground/80 bg-muted/40 px-2 py-0.5 rounded border border-border/40">
            {status.cwd.split(/[/\\]/).pop()}
          </div>
        )}

        <button
          type="button"
          onClick={onOpenSettings}
          className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition"
          title="设置"
        >
          <Settings className="size-4" />
        </button>
      </div>
    </header>
  );
}
