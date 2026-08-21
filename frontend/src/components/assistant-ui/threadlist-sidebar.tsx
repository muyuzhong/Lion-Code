import React, { useState } from "react";
import {
  FolderIcon,
  PlusCircleIcon,
  SearchIcon,
  ArrowUpDownIcon,
  PlusIcon,
  SettingsIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  SunIcon,
  MoonIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
} from "lucide-react";
import { DeepSeekHarnessLogo } from "@/components/icons/logo";
import { cn } from "@/lib/utils";

interface WorkspaceGroup {
  id: string;
  name: string;
  isOpen: boolean;
  sessions: {
    id: string;
    title: string;
    timeAgo: string;
    isActive?: boolean;
  }[];
}

const INITIAL_WORKSPACES: WorkspaceGroup[] = [
  {
    id: "lion-code",
    name: "Lion-Code",
    isOpen: true,
    sessions: [
      {
        id: "sess-1",
        title: "你现在要继续重构仓库: https:",
        timeAgo: "2天",
        isActive: true,
      },
      {
        id: "sess-2",
        title: "# 任务: 按仓库内 Agent Not...",
        timeAgo: "3天",
      },
      {
        id: "sess-3",
        title: "/dsh-find-simplifications",
        timeAgo: "3天",
      },
    ],
  },
  {
    id: "desktop",
    name: "桌面",
    isOpen: true,
    sessions: [
      {
        id: "sess-4",
        title: "当前skill都有什么",
        timeAgo: "3天",
      },
      {
        id: "sess-5",
        title: "找出未试用客户清单",
        timeAgo: "4天",
      },
    ],
  },
  {
    id: "shixi",
    name: "shixi",
    isOpen: true,
    sessions: [
      {
        id: "sess-6",
        title: "财务共享智能作业助理分析",
        timeAgo: "2天",
      },
      {
        id: "sess-7",
        title: "# M7 新会话提示词 (可直接复...",
        timeAgo: "4天",
      },
      {
        id: "sess-8",
        title: "# M6 新会话提示词 (可直接复...",
        timeAgo: "5天",
      },
      {
        id: "sess-9",
        title: "# M5 新会话提示词 (可直接复...",
        timeAgo: "5天",
      },
      {
        id: "sess-10",
        title: "# M4 新会话提示词 (可直接复...",
        timeAgo: "5天",
      },
      {
        id: "sess-11",
        title: "# M3 新会话提示词 (可直接复...",
        timeAgo: "5天",
      },
      {
        id: "sess-12",
        title: "你是财务共享作业助理项目的",
        timeAgo: "5天",
      },
    ],
  },
  {
    id: "yongyou",
    name: "YongYou",
    isOpen: false,
    sessions: [],
  },
];

interface ThreadListSidebarProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onNewSession?: () => void;
  currentTheme?: "light" | "dark";
  onToggleTheme?: () => void;
}

export function ThreadListSidebar({
  collapsed = false,
  onToggleCollapse,
  onNewSession,
  currentTheme = "light",
  onToggleTheme,
}: ThreadListSidebarProps) {
  const [workspaces, setWorkspaces] = useState<WorkspaceGroup[]>(INITIAL_WORKSPACES);
  const [activeSessionId, setActiveSessionId] = useState<string>("sess-1");

  const toggleWorkspace = (id: string) => {
    setWorkspaces((prev) =>
      prev.map((w) => (w.id === id ? { ...w, isOpen: !w.isOpen } : w))
    );
  };

  if (collapsed) {
    return (
      <aside className="w-14 border-r bg-sidebar flex flex-col items-center py-3 justify-between shrink-0 select-none">
        <button
          onClick={onToggleCollapse}
          className="p-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted/80"
          title="展开侧边栏"
        >
          <PanelLeftOpenIcon className="size-5" />
        </button>
        <button
          onClick={onNewSession}
          className="p-2 text-primary hover:bg-primary/10 rounded-lg"
          title="新会话"
        >
          <PlusCircleIcon className="size-5" />
        </button>
        <button
          onClick={onToggleTheme}
          className="p-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted/80"
          title="切换主题"
        >
          {currentTheme === "dark" ? <SunIcon className="size-5" /> : <MoonIcon className="size-5" />}
        </button>
      </aside>
    );
  }

  return (
    <aside className="w-[260px] border-r bg-sidebar flex flex-col h-full shrink-0 select-none text-[13px]">
      {/* 顶部 Logo 与折叠按钮 */}
      <div className="flex h-14 items-center justify-between px-4 border-b">
        <DeepSeekHarnessLogo />
        <button
          onClick={onToggleCollapse}
          className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted/60 transition-colors"
          title="折叠侧边栏"
        >
          <PanelLeftCloseIcon className="size-4" />
        </button>
      </div>

      {/* 新建会话大圆角按钮 */}
      <div className="p-3">
        <button
          onClick={onNewSession}
          className="w-full flex items-center justify-center gap-2 py-2 px-3 border rounded-xl bg-card hover:bg-muted text-foreground font-medium shadow-xs transition-colors cursor-pointer"
        >
          <PlusCircleIcon className="size-4 text-muted-foreground" />
          <span>新会话</span>
        </button>
      </div>

      {/* 工作区标题行 */}
      <div className="flex items-center justify-between px-4 py-1 text-xs text-muted-foreground font-medium">
        <span>工作区</span>
        <div className="flex items-center gap-2">
          <button className="hover:text-foreground p-0.5 rounded" title="搜索">
            <SearchIcon className="size-3.5" />
          </button>
          <button className="hover:text-foreground p-0.5 rounded" title="排序/切换">
            <ArrowUpDownIcon className="size-3.5" />
          </button>
          <button className="hover:text-foreground p-0.5 rounded" title="新建工作区">
            <PlusIcon className="size-3.5" />
          </button>
        </div>
      </div>

      {/* 工作区分组树与会话列表 */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-3">
        {workspaces.map((ws) => (
          <div key={ws.id} className="space-y-0.5">
            {/* 工作区头部 */}
            <button
              onClick={() => toggleWorkspace(ws.id)}
              className="w-full flex items-center gap-1.5 px-2 py-1 text-xs font-semibold text-foreground/80 hover:text-foreground rounded hover:bg-muted/60 cursor-pointer"
            >
              <FolderIcon className="size-3.5 text-blue-500 fill-blue-500/20 shrink-0" />
              <span className="truncate flex-1 text-left">{ws.name}</span>
              {ws.sessions.length > 0 && (
                ws.isOpen ? (
                  <ChevronDownIcon className="size-3 text-muted-foreground shrink-0" />
                ) : (
                  <ChevronRightIcon className="size-3 text-muted-foreground shrink-0" />
                )
              )}
            </button>

            {/* 会话列表 */}
            {ws.isOpen && ws.sessions.length > 0 && (
              <div className="pl-3 pr-1 space-y-0.5">
                {ws.sessions.map((sess) => {
                  const isActive = activeSessionId === sess.id;
                  return (
                    <button
                      key={sess.id}
                      onClick={() => setActiveSessionId(sess.id)}
                      className={cn(
                        "w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-colors group cursor-pointer",
                        isActive
                          ? "bg-secondary text-foreground font-medium shadow-2xs"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                      )}
                    >
                      <span className="truncate pr-2 text-xs leading-tight">
                        {sess.title}
                      </span>
                      <span className="text-[11px] text-muted-foreground/70 shrink-0">
                        {sess.timeAgo}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 底部常驻设置与主题切换栏 */}
      <div className="p-3 border-t flex items-center justify-between">
        <button
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground py-1 px-2 rounded-lg hover:bg-muted/60 transition-colors"
        >
          <SettingsIcon className="size-4" />
          <span>设置</span>
        </button>

        {/* 亮色/暗色主题快速切换 */}
        <button
          onClick={onToggleTheme}
          className="p-1.5 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted transition-colors"
          title={currentTheme === "dark" ? "切换到白色主题" : "切换到黑色主题"}
        >
          {currentTheme === "dark" ? (
            <SunIcon className="size-4 text-amber-500" />
          ) : (
            <MoonIcon className="size-4 text-slate-600" />
          )}
        </button>
      </div>
    </aside>
  );
}
