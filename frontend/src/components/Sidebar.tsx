import React, { useState } from 'react';
import {
  Clock,
  FolderGit2,
  MessageSquare,
  Plus,
  Search,
  Sparkles,
  Zap,
} from 'lucide-react';
import { SessionSummary, SkillItem } from '../types';

interface SidebarProps {
  isOpen: boolean;
  activeTab: 'chat' | 'skills' | 'workspace';
  sessions: SessionSummary[];
  currentSessionId?: string;
  cwd?: string;
  skills: SkillItem[];
  onNewSession: () => void;
  onResumeSession: (sessionId: string) => void;
  onSkillClick: (skillName: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  activeTab,
  sessions,
  currentSessionId,
  cwd,
  skills,
  onNewSession,
  onResumeSession,
  onSkillClick,
}) => {
  const [searchQuery, setSearchQuery] = useState('');

  if (!isOpen) return null;

  const filteredSessions = sessions.filter((s) => {
    if (!searchQuery) return true;
    return s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (s.startTime && s.startTime.includes(searchQuery));
  });

  return (
    <div className="w-72 h-full flex flex-col bg-[#121826] border-r border-white/[0.08] z-20 flex-shrink-0 select-none animate-in fade-in slide-in-from-left-4 duration-200">
      {activeTab === 'chat' && (
        <>
          {/* 头部与新建按钮 */}
          <div className="p-3.5 space-y-3 border-b border-white/[0.08]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold tracking-tight text-slate-200 flex items-center gap-1.5">
                <MessageSquare className="w-3.5 h-3.5 text-[#4e75ff]" />
                会话历史 (Sessions)
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/[0.06] text-slate-400">
                {sessions.length}
              </span>
            </div>

            <button
              onClick={onNewSession}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-gradient-to-r from-[#4e75ff] to-[#3b82f6] hover:from-[#3d61f5] hover:to-[#2563eb] text-white font-medium text-xs shadow-md shadow-blue-500/20 transition-all active:scale-[0.98]"
            >
              <Plus className="w-4 h-4" />
              <span>新建会话 (New Chat)</span>
            </button>

            {/* 搜索框 */}
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索会话..."
                className="w-full pl-8 pr-3 py-1.5 rounded-lg text-xs bg-[#1a2338] border border-white/[0.08] focus:border-[#4e75ff]/60 text-slate-100 placeholder-slate-500 focus:outline-none transition-colors"
              />
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2" />
            </div>
          </div>

          {/* 会话列表 */}
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {filteredSessions.length === 0 ? (
              <div className="py-12 text-center text-xs text-slate-500">
                暂无匹配会话
              </div>
            ) : (
              filteredSessions.map((sess) => {
                const isSelected = sess.id === currentSessionId;
                const timeStr = sess.startTime
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
                    className={`w-full group relative flex items-center justify-between p-2.5 rounded-xl text-xs text-left transition-all ${
                      isSelected
                        ? 'bg-[#1a2338] border-l-2 border-[#4e75ff] shadow-sm font-medium text-white pl-3'
                        : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className={`w-2 h-2 rounded-full ${isSelected ? 'bg-[#4e75ff] shadow-sm shadow-blue-500/80' : 'bg-slate-700'}`} />
                      <div className="truncate">
                        <div className="truncate font-medium">{timeStr}</div>
                        <div className="text-[10px] text-slate-500 font-mono truncate">
                          ID: {sess.id.slice(0, 8)}
                        </div>
                      </div>
                    </div>

                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/[0.06] text-slate-400">
                      {sess.messageCount}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </>
      )}

      {activeTab === 'skills' && (
        <div className="flex-1 flex flex-col p-3.5 space-y-3 overflow-hidden">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
            <Zap className="w-4 h-4 text-amber-400" />
            <span>可用 Skill 列表 ({skills.length})</span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {skills.map((skill) => (
              <button
                key={skill.name}
                onClick={() => onSkillClick(skill.name)}
                className="w-full text-left p-2.5 rounded-xl border border-white/[0.08] bg-[#1a2338]/60 hover:border-[#4e75ff]/40 hover:bg-[#1a2338] transition-all group"
              >
                <div className="flex items-center justify-between text-xs font-mono font-semibold text-[#4e75ff] mb-1">
                  <span>/{skill.name}</span>
                  <Sparkles className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-[#4e75ff]" />
                </div>
                {skill.description && (
                  <p className="text-[11px] text-slate-400 line-clamp-2">
                    {skill.description}
                  </p>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'workspace' && (
        <div className="flex-1 p-3.5 space-y-4 text-xs">
          <div className="flex items-center gap-1.5 font-semibold text-slate-200">
            <FolderGit2 className="w-4 h-4 text-[#4e75ff]" />
            <span>工作区路径 (CWD)</span>
          </div>

          <div className="p-3 rounded-xl border border-white/[0.08] bg-[#0b0f19] font-mono text-[11px] text-slate-300 break-all">
            {cwd || '未指定工作区'}
          </div>

          <div className="flex items-center gap-1.5 text-slate-400 text-[11px]">
            <Clock className="w-3.5 h-3.5" />
            <span>DeepSeek Harness 运行时环境已就绪</span>
          </div>
        </div>
      )}
    </div>
  );
};
