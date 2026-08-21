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
    <aside className="w-16 h-full flex flex-col items-center justify-between py-3.5 bg-neutral-100/80 dark:bg-neutral-950/90 border-r border-neutral-200/80 dark:border-neutral-800/80 z-30 flex-shrink-0 select-none">
      {/* 顶部：Lion Logo */}
      <div className="flex flex-col items-center gap-5">
        <div className="relative group cursor-pointer">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-600 p-[1.5px] shadow-lg shadow-purple-500/20 transition-transform group-hover:scale-105">
            <div className="w-full h-full rounded-[10px] bg-neutral-900 flex items-center justify-center text-lg">
              🦁
            </div>
          </div>
        </div>

        {/* 导航图标 */}
        <div className="flex flex-col items-center gap-2">
          <button
            onClick={() => onTabChange('chat')}
            className={`relative p-2.5 rounded-xl transition-all ${
              activeTab === 'chat'
                ? 'bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 shadow-md shadow-neutral-900/10'
                : 'text-neutral-500 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-200/60 dark:hover:bg-neutral-800/60'
            }`}
            title="对话 (Chat)"
          >
            <MessageSquare className="w-5 h-5" />
          </button>

          <button
            onClick={() => onTabChange('skills')}
            className={`relative p-2.5 rounded-xl transition-all ${
              activeTab === 'skills'
                ? 'bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 shadow-md shadow-neutral-900/10'
                : 'text-neutral-500 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-200/60 dark:hover:bg-neutral-800/60'
            }`}
            title="技能中心 (Skills)"
          >
            <Zap className="w-5 h-5" />
          </button>

          <button
            onClick={() => onTabChange('workspace')}
            className={`relative p-2.5 rounded-xl transition-all ${
              activeTab === 'workspace'
                ? 'bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 shadow-md shadow-neutral-900/10'
                : 'text-neutral-500 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-200/60 dark:hover:bg-neutral-800/60'
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
          className="p-2.5 rounded-xl text-neutral-500 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-200/60 dark:hover:bg-neutral-800/60 transition-colors"
          title={isSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
        >
          {isSidebarOpen ? <PanelLeftClose className="w-5 h-5" /> : <PanelLeftOpen className="w-5 h-5" />}
        </button>

        <button
          onClick={onToggleTheme}
          className="p-2.5 rounded-xl text-neutral-500 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-200/60 dark:hover:bg-neutral-800/60 transition-colors"
          title={isDark ? '切换至浅色模式' : '切换至深色模式'}
        >
          {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>

        <button
          onClick={onOpenSettings}
          className="p-2.5 rounded-xl text-neutral-500 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-200/60 dark:hover:bg-neutral-800/60 transition-colors"
          title="模型与系统设置"
        >
          <Settings className="w-5 h-5" />
        </button>
      </div>
    </aside>
  );
};
