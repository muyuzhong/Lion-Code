import React from "react";
import { Plus, MessageSquare, Settings, Coins, PanelLeftClose } from "lucide-react";
import { ServerStatus, SessionSummary } from "@/types/chat";
import { cn } from "@/lib/utils";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: SessionSummary[];
  currentSessionId?: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
  status: ServerStatus | null;
}

export function Sidebar({
  isOpen,
  onClose,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewSession,
  onOpenSettings,
  status,
}: SidebarProps) {
  if (!isOpen) return null;

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border/50 bg-sidebar text-sidebar-foreground transition-all duration-300 md:static">
      {/* Sidebar Header */}
      <div className="flex h-13 items-center justify-between px-4 border-b border-border/30">
        <div className="flex items-center gap-2 font-semibold text-xs text-foreground tracking-tight">
          <span className="text-base">🦁</span>
          <span>Lion Code</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition"
        >
          <PanelLeftClose className="size-4" />
        </button>
      </div>

      {/* New Chat Button */}
      <div className="p-3">
        <button
          type="button"
          onClick={onNewSession}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 text-xs font-medium text-primary-foreground shadow-xs hover:opacity-90 transition"
        >
          <Plus className="size-3.5" />
          <span>新建对话 (New Chat)</span>
        </button>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1 py-1">
        <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
          历史会话 (Sessions)
        </div>

        {sessions.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground/60">
            暂无历史会话
          </div>
        ) : (
          sessions.map((sess) => {
            const isActive = sess.id === currentSessionId;
            const timeLabel = sess.startTime ? new Date(sess.startTime).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
            const dateLabel = sess.startTime ? new Date(sess.startTime).toLocaleDateString([], { month: "numeric", day: "numeric" }) : "";

            return (
              <button
                key={sess.id}
                type="button"
                onClick={() => onSelectSession(sess.id)}
                className={cn(
                  "flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs transition",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-2xs"
                    : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <MessageSquare className="size-3.5 shrink-0 opacity-70" />
                  <span className="truncate">{sess.id.slice(0, 16)}</span>
                </div>
                <div className="text-[10px] text-muted-foreground/60 shrink-0 ml-2">
                  {dateLabel} {timeLabel}
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* Sidebar Footer */}
      <div className="border-t border-border/30 p-3 space-y-2 text-xs bg-sidebar/50">
        {/* Token Usage Stats */}
        {status && (
          <div className="flex items-center justify-between px-2 py-1 rounded bg-muted/20 text-[11px] text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Coins className="size-3.5 text-amber-500" />
              <span>Token 消耗</span>
            </div>
            <span className="font-mono">{status.input_tokens + status.output_tokens}</span>
          </div>
        )}

        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition"
        >
          <Settings className="size-3.5" />
          <span>设置与模型配置</span>
        </button>
      </div>
    </aside>
  );
}
