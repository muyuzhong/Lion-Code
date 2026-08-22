import React, { useState } from "react";
import { Plus, MessageSquare, Coins, PanelLeftClose, Folder, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import { ServerStatus, SessionSummary, SkillItem } from "@/types/chat";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: SessionSummary[];
  currentSessionId?: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  status: ServerStatus | null;
  skills: SkillItem[];
  onSelectSkill: (name: string) => void;
}

// 纯前端相对时间：后端只有 ISO 时间戳，不引日期库；按自然日差值分档
function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000);
  if (dayDiff === 0) return `今天 ${time}`;
  if (dayDiff === 1) return `昨天 ${time}`;
  if (dayDiff < 7) return `${dayDiff} 天前`;
  if (date.getFullYear() !== new Date().getFullYear()) {
    return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
  }
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

export function Sidebar({
  isOpen,
  onClose,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewSession,
  status,
  skills,
  onSelectSkill,
}: SidebarProps) {
  const [skillsOpen, setSkillsOpen] = useState(false);

  if (!isOpen) return null;

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 transition-all duration-300 md:static">
      {/* Sidebar Header */}
      <div className="flex h-13 items-center justify-between px-4 border-b border-zinc-200 dark:border-zinc-800/80">
        <div className="flex items-center gap-2 font-semibold text-xs text-zinc-900 dark:text-zinc-100 tracking-tight">
          <span className="text-base">🦁</span>
          <span>Lion Code</span>
          <span className="rounded bg-zinc-200/80 dark:bg-zinc-800 px-1.5 py-0.5 text-[10px] font-mono text-zinc-600 dark:text-zinc-400">
            Agent
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex size-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-900 hover:text-zinc-900 dark:hover:text-zinc-100 transition"
        >
          <PanelLeftClose className="size-4" />
        </button>
      </div>

      {/* New Chat Button */}
      <div className="p-3">
        <button
          type="button"
          onClick={onNewSession}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-900 dark:bg-zinc-100 text-zinc-100 dark:text-zinc-900 px-3 py-2 text-xs font-medium shadow-xs hover:opacity-90 transition"
        >
          <Plus className="size-3.5" />
          <span>新建会话 (New Chat)</span>
        </button>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1 py-1">
        <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
          历史会话 (Sessions)
        </div>

        {sessions.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-zinc-400 dark:text-zinc-500">
            暂无历史会话记录
          </div>
        ) : (
          sessions.map((sess) => {
            const isActive = sess.id === currentSessionId;
            const relativeTime = sess.startTime ? formatRelativeTime(sess.startTime) : "";

            return (
              <button
                key={sess.id}
                type="button"
                onClick={() => onSelectSession(sess.id)}
                className={`flex w-full flex-col items-start rounded-lg px-2.5 py-2 text-left text-xs transition ${
                  isActive
                    ? "bg-white dark:bg-zinc-900 font-medium text-zinc-900 dark:text-zinc-100 shadow-2xs border border-zinc-200/80 dark:border-zinc-800"
                    : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-900/60 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                <div className="flex w-full items-center gap-2 min-w-0">
                  <MessageSquare className="size-3.5 shrink-0 opacity-60" />
                  <span className="truncate font-mono">{sess.id.slice(0, 16)}</span>
                </div>
                <div className="mt-0.5 ml-[22px] text-[10px] text-zinc-400 dark:text-zinc-500">
                  {sess.messageCount} 条消息{relativeTime ? ` · ${relativeTime}` : ""}
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* Sidebar Footer */}
      <div className="border-t border-zinc-200 dark:border-zinc-800 p-3 space-y-2 text-xs bg-zinc-100/50 dark:bg-zinc-950/60">
        {/* Workspace directory */}
        {status?.cwd && (
          <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-[11px] text-zinc-600 dark:text-zinc-400">
            <div className="flex items-center gap-1.5 truncate">
              <Folder className="size-3.5 shrink-0 text-blue-500" />
              <span className="truncate font-mono">{status.cwd.split(/[/\\]/).pop()}</span>
            </div>
          </div>
        )}

        {/* 可用 Skills：拉取失败静默降级为空列表，此时整个区块隐藏 */}
        {skills.length > 0 && (
          <div className="rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-[11px] text-zinc-600 dark:text-zinc-400">
            <button
              type="button"
              onClick={() => setSkillsOpen((prev) => !prev)}
              className="flex w-full items-center justify-between px-2.5 py-1.5 hover:text-zinc-900 dark:hover:text-zinc-100 transition"
            >
              <span className="flex items-center gap-1.5">
                <Sparkles className="size-3.5 text-violet-500" />
                <span>可用 Skills</span>
              </span>
              <span className="flex items-center gap-1 font-mono">
                {skills.length}
                {skillsOpen ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              </span>
            </button>
            {skillsOpen && (
              /* 限高避免长列表把 footer 其他信息挤出视口 */
              <div className="max-h-40 overflow-y-auto border-t border-zinc-200 dark:border-zinc-800 py-1">
                {skills.map((skill) => (
                  <button
                    key={skill.name}
                    type="button"
                    onClick={() => onSelectSkill(skill.name)}
                    title={skill.description ?? undefined}
                    className="flex w-full flex-col items-start gap-0.5 px-2.5 py-1 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800/60 transition"
                  >
                    <span className="w-full truncate font-mono text-[10px] text-zinc-700 dark:text-zinc-300">
                      {skill.name}
                    </span>
                    {skill.description && (
                      <span className="w-full truncate text-[10px] text-zinc-400 dark:text-zinc-500">
                        {skill.description}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Token Usage Stats */}
        {status && (
          <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-[11px] text-zinc-600 dark:text-zinc-400">
            <div className="flex items-center gap-1.5">
              <Coins className="size-3.5 text-amber-500" />
              <span>Token 消耗</span>
            </div>
            <span className="font-mono font-medium text-zinc-900 dark:text-zinc-100">
              {status.input_tokens + status.output_tokens}
            </span>
          </div>
        )}
      </div>
    </aside>
  );
}
