import { MessageSquarePlus, PanelLeft, Search } from "lucide-react";

export function ConversationTopbar({ title, transportStatus, transportLabel, sidebarCollapsed, onToggleSidebar, onCreateSession, onOpenSearch }: {
  title: string;
  transportStatus: string;
  transportLabel: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onCreateSession: () => void;
  onOpenSearch: () => void;
}) {
  const displayTitle = truncateTitle(title);
  return (
    <header className="conversation-topbar" role="toolbar" aria-label="会话工具栏">
      <div className="ct-left">
        {sidebarCollapsed ? <button className="ct-icon-btn" type="button" aria-label="展开侧栏" onClick={onToggleSidebar}><PanelLeft aria-hidden="true" size={16} /></button> : null}
        <strong title={title}># {displayTitle}</strong>
      </div>
      <div className="ct-actions">
        <span className={`transport-indicator ${transportStatus}`} aria-label={transportLabel} title={transportLabel}><i aria-hidden="true" /></span>
        <button className="ct-icon-btn" type="button" aria-label="新建任务" onClick={onCreateSession}><MessageSquarePlus aria-hidden="true" size={16} /></button>
        <button className="ct-icon-btn" type="button" aria-label="搜索会话" onClick={onOpenSearch}><Search aria-hidden="true" size={16} /></button>
      </div>
    </header>
  );
}

function truncateTitle(title: string): string {
  const characters = Array.from(title);
  return characters.length > 14 ? `${characters.slice(0, 14).join("")}…` : title;
}
