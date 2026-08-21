import React from 'react';
import {
  FolderGit2,
  MessageSquare,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sun,
  Zap,
} from 'lucide-react';

interface DockProps {
  activeTab: 'chat' | 'skills' | 'workspace';
  onTabChange: (tab: 'chat' | 'skills' | 'workspace') => void;
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  onOpenSettings: () => void;
  isDark: boolean;
  onToggleTheme: () => void;
}

export const Dock: React.FC<DockProps> = ({
  activeTab,
  onTabChange,
  isSidebarOpen,
  onToggleSidebar,
  onOpenSettings,
  isDark,
  onToggleTheme,
}) => {
  return (
    <aside className="w-16 h-full flex flex-col items-center justify-between py-3.5 bg-[#0f1422] border-r border-white/[0.08] z-30 flex-shrink-0 select-none">
      {/* 顶部：DeepSeek Harness 标志 */}
      <div className="flex flex-col items-center gap-5">
        <div className="relative group cursor-pointer">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-[#4e75ff] to-[#3b82f6] p-[1.5px] shadow-lg shadow-blue-500/25 transition-transform group-hover:scale-105">
            <div className="w-full h-full rounded-[10px] bg-[#121827] flex items-center justify-center text-lg">
              🐋
            </div>
          </div>
        </div>

        {/* 导航图标 */}
        <div className="flex flex-col items-center gap-2">
          <button
            onClick={() => onTabChange('chat')}
            className={`relative p-2.5 rounded-xl transition-all ${
              activeTab === 'chat'
                ? 'bg-[#4e75ff] text-white shadow-md shadow-blue-500/25'
                : 'text-slate-400 hover:text-white hover:bg-white/[0.06]'
            }`}
            title="对话 (Chat)"
          >
            <MessageSquare className="w-5 h-5" />
          </button>

          <button
            onClick={() => onTabChange('skills')}
            className={`relative p-2.5 rounded-xl transition-all ${
              activeTab === 'skills'
                ? 'bg-[#4e75ff] text-white shadow-md shadow-blue-500/25'
                : 'text-slate-400 hover:text-white hover:bg-white/[0.06]'
            }`}
            title="技能中心 (Skills)"
          >
            <Zap className="w-5 h-5" />
          </button>

          <button
            onClick={() => onTabChange('workspace')}
            className={`relative p-2.5 rounded-xl transition-all ${
              activeTab === 'workspace'
                ? 'bg-[#4e75ff] text-white shadow-md shadow-blue-500/25'
                : 'text-slate-400 hover:text-white hover:bg-white/[0.06]'
            }`}
            title="工作区信息 (Workspace)"
          >
            <FolderGit2 className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* 底部：侧边栏切换、主题、设置 */}
      <div className="flex flex-col items-center gap-2">
        <button
          onClick={onToggleSidebar}
          className="p-2.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
          title={isSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
        >
          {isSidebarOpen ? <PanelLeftClose className="w-5 h-5" /> : <PanelLeftOpen className="w-5 h-5" />}
        </button>

        <button
          onClick={onToggleTheme}
          className="p-2.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
          title={isDark ? '切换至浅色模式' : '切换至深色模式'}
        >
          {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>

        <button
          onClick={onOpenSettings}
          className="p-2.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
          title="模型与系统设置"
        >
          <Settings className="w-5 h-5" />
        </button>
      </div>
    </aside>
  );
};
