import React from 'react';
import {
  FolderGit2,
  MessageSquare,
  Plus,
  Zap,
} from 'lucide-react';
import { SessionSummary, SkillItem } from '../types';

interface SidebarProps {
  isOpen: boolean;
  sessions: SessionSummary[];
  currentSessionId?: string;
  cwd?: string;
  skills: SkillItem[];
  onNewSession: () => void;
  onResumeSession: (sessionId: string) => void;
  onClose: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  sessions,
  currentSessionId,
  cwd,
  skills,
  onNewSession,
  onResumeSession,
}) => {
  return (
    <aside
      className={`${
        isOpen ? 'w-64 translate-x-0' : '-translate-x-full lg:w-0 lg:translate-x-0'
      } fixed lg:static top-14 bottom-0 left-0 z-20 flex flex-col bg-neutral-50 dark:bg-neutral-950/90 border-r border-neutral-200 dark:border-neutral-800 transition-all duration-300 overflow-hidden flex-shrink-0`}
    >
      {/* 新建会话按钮 */}
      <div className="p-3">
        <button
          onClick={onNewSession}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-neutral-900 dark:bg-neutral-100 hover:bg-neutral-800 dark:hover:bg-white text-white dark:text-neutral-900 font-medium text-xs shadow-sm transition-all"
        >
          <Plus className="w-4 h-4" />
          <span>新建会话 (New Chat)</span>
        </button>
      </div>

      {/* 工作区路径 */}
      {cwd && (
        <div className="px-3 py-2 border-b border-neutral-200/60 dark:border-neutral-800/60 flex items-center gap-2 text-xs text-neutral-400">
          <FolderGit2 className="w-3.5 h-3.5 text-neutral-500 flex-shrink-0" />
          <span className="font-mono text-[11px] truncate" title={cwd}>
            {cwd.split(/[\\/]/).pop() || cwd}
          </span>
        </div>
      )}

      {/* 历史会话列表 */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-1">
        <div className="px-2 text-[10px] font-semibold tracking-wider uppercase text-neutral-400 mb-1">
          最近会话
        </div>

        {sessions.length === 0 ? (
          <div className="px-2 py-4 text-xs text-neutral-400 text-center">暂无历史会话</div>
        ) : (
          sessions.map((sess) => {
            const isSelected = sess.id === currentSessionId;
            const dateStr = sess.startTime
              ? new Date(sess.startTime).toLocaleDateString([], {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : sess.id;

            return (
              <button
                key={sess.id}
                onClick={() => onResumeSession(sess.id)}
                className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs text-left transition-colors ${
                  isSelected
                    ? 'bg-neutral-200/80 dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 font-medium'
                    : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-900'
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  <MessageSquare className="w-3.5 h-3.5 text-neutral-400 flex-shrink-0" />
                  <span className="truncate">{dateStr}</span>
                </div>
                <span className="text-[10px] font-mono text-neutral-400">
                  {sess.messageCount} 条
                </span>
              </button>
            );
          })
        )}
      </div>

      {/* 技能列表 */}
      {skills.length > 0 && (
        <div className="p-3 border-t border-neutral-200/60 dark:border-neutral-800/60">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-neutral-500 mb-2">
            <Zap className="w-3.5 h-3.5 text-amber-500" />
            <span>可用技能 ({skills.length})</span>
          </div>
          <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
            {skills.map((skill) => (
              <span
                key={skill.name}
                className="text-[10px] px-1.5 py-0.5 rounded bg-neutral-200/60 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 font-mono"
                title={skill.description}
              >
                /{skill.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
};
