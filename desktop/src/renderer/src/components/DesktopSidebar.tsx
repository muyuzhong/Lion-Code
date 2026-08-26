import {
  Bell,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Moon,
  PanelLeft,
  Plus,
  Search,
  Settings,
  Pencil,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

interface SessionItem {
  id: string;
  label: string | null;
  startTime: string | null;
  messageCount: number;
}

interface SkillItem {
  name: string;
  description: string | null;
}

export function DesktopSidebar({
  workspaceName,
  sessions,
  activeSessionId,
  skills,
  isStreaming,
  theme,
  formatTime,
  onCreateSession,
  onSwitchSession,
  onRenameSession,
  onSelectSkill,
  onOpenSettings,
  onToggleTheme,
  onDisconnect,
  onCollapse,
  searchOpen,
  onSearchOpenChange,
  onResizeStart,
  onResizeBy,
}: {
  workspaceName: string;
  sessions: SessionItem[];
  activeSessionId: string | undefined;
  skills: SkillItem[];
  isStreaming: boolean;
  theme: "light" | "dark";
  formatTime: (value: string | null) => string;
  onCreateSession: () => void;
  onSwitchSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, label: string) => Promise<boolean>;
  onSelectSkill: (skillName: string) => void;
  onOpenSettings: () => void;
  onToggleTheme: () => void;
  onDisconnect: () => void;
  onCollapse: () => void;
  searchOpen: boolean;
  onSearchOpenChange: (open: boolean) => void;
  onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onResizeBy: (delta: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [projectOpen, setProjectOpen] = useState(true);
  const searchInput = useRef<HTMLInputElement>(null);
  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0];
  const visibleSessions = query.trim()
    ? sessions.filter((session) => `${session.label ?? ""} ${session.id}`.toLowerCase().includes(query.trim().toLowerCase()))
    : sessions;
  useEffect(() => {
    if (searchOpen) requestAnimationFrame(() => searchInput.current?.focus());
  }, [searchOpen]);
  return (
    <aside className="sidebar" aria-label="工作区与会话">
      <header className="sidebar-header">
        <span className="sidebar-product">Lion</span>
        <div className="sidebar-header-actions">
          <button type="button" className={`chrome-icon ${searchOpen ? "active" : ""}`} aria-label="搜索会话" aria-pressed={searchOpen} onClick={() => onSearchOpenChange(!searchOpen)}><Search aria-hidden="true" size={16} /></button>
          <button type="button" className="chrome-icon" aria-label="折叠侧栏" onClick={onCollapse}><PanelLeft aria-hidden="true" size={16} /></button>
        </div>
      </header>

      <div className="sidebar-body">
        {searchOpen ? <div className="sidebar-search"><Search aria-hidden="true" size={14} /><input ref={searchInput} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索会话" aria-label="搜索会话" /><button type="button" aria-label="关闭搜索" onClick={() => { setQuery(""); onSearchOpenChange(false); }}><X aria-hidden="true" size={14} /></button></div> : null}
        <section className="sidebar-section">
          <div className="sidebar-section-label">会话</div>
          {activeSession ? <SessionRow session={activeSession} active formatTime={formatTime} disabled renameDisabled={isStreaming} onRename={onRenameSession} /> : <p className="sidebar-empty">暂无会话</p>}
        </section>

        <section className="sidebar-section projects-section">
          <div className="sidebar-section-label">项目</div>
          <div className="project-group">
            <div className="project-row">
              <button type="button" className="project-toggle" aria-expanded={projectOpen} onClick={() => setProjectOpen((open) => !open)}>
                {projectOpen ? <ChevronDown aria-hidden="true" size={14} /> : <ChevronRight aria-hidden="true" size={14} />}
                <Folder aria-hidden="true" size={15} />
                <strong>{workspaceName}</strong>
                <span className="project-active-dot" aria-label="当前项目" />
              </button>
              <button type="button" aria-label="新建任务" onClick={onCreateSession} disabled={isStreaming}><Plus aria-hidden="true" size={14} /></button>
            </div>
            <div className={`project-sessions ${projectOpen ? "" : "collapsed"}`}>
              {visibleSessions.map((session) => (
                <SessionRow
                  key={session.id}
                  session={session}
                  active={session.id === activeSessionId}
                  formatTime={formatTime}
                  disabled={isStreaming || session.id === activeSessionId}
                  renameDisabled={isStreaming}
                  onClick={() => onSwitchSession(session.id)}
                  onRename={onRenameSession}
                />
              ))}
              {sessions.length === 0 ? <p className="sidebar-empty">新任务会出现在这里。</p> : null}
              {sessions.length > 0 && visibleSessions.length === 0 ? <p className="sidebar-empty">没有匹配的会话。</p> : null}
            </div>
          </div>
        </section>

        <details className="sidebar-skills">
          <summary><span>Skills</span><small>{skills.length}</small></summary>
          <div>{skills.map((skill) => <button key={skill.name} type="button" onClick={() => onSelectSkill(skill.name)}><strong>{skill.name}</strong><small>{skill.description || "项目技能"}</small></button>)}</div>
        </details>

        <footer className="sidebar-footer">
          <button type="button" aria-label="打开设置" onClick={onOpenSettings}><Settings aria-hidden="true" size={16} /></button>
          <button type="button" aria-label="切换工作区" onClick={onDisconnect}><FolderOpen aria-hidden="true" size={16} /></button>
          <details className="sidebar-notifications"><summary aria-label="通知"><Bell aria-hidden="true" size={16} /></summary><div><strong>暂无通知</strong><span>新的运行提醒会显示在这里。</span></div></details>
          <button type="button" aria-label={`切换到${theme === "dark" ? "浅色" : "深色"}主题`} onClick={onToggleTheme}>{theme === "dark" ? <Sun aria-hidden="true" size={16} /> : <Moon aria-hidden="true" size={16} />}</button>
          <span>v1.0.0</span>
        </footer>
      </div>
      <div
        className="sidebar-resize"
        role="separator"
        aria-label="调整侧栏宽度"
        aria-orientation="vertical"
        tabIndex={0}
        onPointerDown={onResizeStart}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") { event.preventDefault(); onResizeBy(-10); }
          if (event.key === "ArrowRight") { event.preventDefault(); onResizeBy(10); }
        }}
      />
    </aside>
  );
}

function SessionRow({ session, active, formatTime, disabled = false, renameDisabled = false, onClick, onRename }: { session: SessionItem; active: boolean; formatTime: (value: string | null) => string; disabled?: boolean; renameDisabled?: boolean; onClick?: () => void; onRename: (sessionId: string, label: string) => Promise<boolean> }) {
  const [renaming, setRenaming] = useState(false);
  const [label, setLabel] = useState(session.label ?? "");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (renaming) requestAnimationFrame(() => input.current?.select());
  }, [renaming]);
  const save = async () => {
    const next = label.trim();
    if (!next) return;
    if (await onRename(session.id, next)) setRenaming(false);
  };
  const title = session.label || "Untitled Conversation";
  const compactTime = formatCompactTime(session.startTime);
  return (
    <div className={`thread-item ${active ? "active" : ""}`}>
      <button type="button" className="thread-main" disabled={disabled || renaming} onClick={onClick}>
        <span className={`thread-status ${active ? "active" : ""}`} aria-hidden="true" />
        <span className="thread-copy">
          {renaming ? (
            <input
              ref={input}
              aria-label={`重命名 ${title}`}
              value={label}
              maxLength={80}
              onChange={(event) => setLabel(event.target.value)}
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                if (event.key === "Enter") { event.preventDefault(); void save(); }
                else if (event.key === "Escape") { setLabel(session.label ?? ""); setRenaming(false); }
              }}
            />
          ) : (
            <>
              <strong>{title}</strong>
              {compactTime ? <small>{compactTime}</small> : null}
            </>
          )}
        </span>
      </button>
      {!renaming ? (
        <button
          type="button"
          className="thread-rename"
          aria-label={`重命名 ${title}`}
          title="重命名会话"
          disabled={renameDisabled}
          onClick={() => { setLabel(session.label ?? ""); setRenaming(true); }}
        >
          <Pencil aria-hidden="true" size={12} />
        </button>
      ) : null}
    </div>
  );
}

function formatCompactTime(value: string | null, now = Date.now()): string {
  if (!value) return "";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "";
  const elapsed = Math.max(0, now - timestamp);
  if (elapsed < 60_000) return "1m";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}m`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)}h`;
  if (elapsed < 604_800_000) return `${Math.floor(elapsed / 86_400_000)}d`;
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(timestamp);
}

