import { useEffect, useMemo, useRef, useState } from "react";
import type { BackendEndpoint } from "../../shared/types";
import { LionRuntimeProvider, useLionRuntime } from "./assistantRuntime";
import { browserBackendBootstrap } from "./backend";
import { ChatThread } from "./ChatThread";

type Theme = "light" | "dark";

export function WorkspaceShell({ endpoint, workspacePath }: { endpoint: BackendEndpoint; workspacePath: string }) {
  const bootstrap = useMemo(() => browserBackendBootstrap(endpoint), [endpoint.baseUrl, endpoint.capability]);
  return <LionRuntimeProvider bootstrap={bootstrap}><Workspace workspacePath={workspacePath} /></LionRuntimeProvider>;
}

function Workspace({ workspacePath }: { workspacePath: string }) {
  const { adapter, snapshot } = useLionRuntime();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [skillPrompt, setSkillPrompt] = useState<{ key: number; text: string } | null>(null);
  const [theme, setTheme] = useState<Theme>(() => preferredTheme());
  const firstRunShown = useRef(false);
  const workspaceName = workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1) || workspacePath;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lion-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (snapshot.status?.api_configured === false && !firstRunShown.current) {
      firstRunShown.current = true;
      setSettingsOpen(true);
    }
  }, [snapshot.status?.api_configured]);

  return (
    <div className={`workspace-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <a className="skip-link" href="#lion-thread">跳到对话</a>
      <aside className="sidebar" aria-label="工作区与会话">
        <div className="brand-lockup"><span className="brand-mark" aria-hidden="true">L</span><div><strong>Lion</strong><small>desktop agent</small></div></div>
        <div className="workspace-identity"><span className="workspace-kicker">当前工作区</span><strong title={workspacePath}>{workspaceName}</strong><span title={workspacePath}>{workspacePath}</span></div>
        <button className="new-session" type="button" disabled={snapshot.protocol.isStreaming} onClick={() => void adapter.createSession()}><span aria-hidden="true">＋</span> 新建任务</button>
        <nav className="session-nav" aria-label="会话">
          <div className="section-heading"><span>会话</span><small>{snapshot.sessions.length}</small></div>
          <div className="session-list">
            {snapshot.sessions.map((session) => (
              <button
                className={`session-item ${session.id === snapshot.status?.session_id ? "active" : ""}`}
                type="button"
                key={session.id}
                disabled={snapshot.protocol.isStreaming || session.id === snapshot.status?.session_id}
                onClick={() => void adapter.switchSession(session.id)}
              >
                <span>{session.id.slice(0, 12)}</span>
                <small>{session.messageCount} 条消息 · {formatRelativeTime(session.startTime)}</small>
              </button>
            ))}
            {snapshot.sessions.length === 0 ? <p className="sidebar-empty">新任务会在这里留下会话记录。</p> : null}
          </div>
        </nav>
        <details className="skills">
          <summary>可用 Skills <span>{snapshot.skills.length}</span></summary>
          <div>
            {snapshot.skills.map((skill) => <button type="button" key={skill.name} onClick={() => setSkillPrompt({ key: Date.now(), text: `用 ${skill.name} 技能帮我：` })}><strong>{skill.name}</strong><small>{skill.description || "项目技能"}</small></button>)}
            {snapshot.skills.length === 0 ? <p>当前工作区没有可用 Skill。</p> : null}
          </div>
        </details>
        <footer className="sidebar-footer">
          <button type="button" onClick={() => setSettingsOpen(true)}>设置</button>
          <button type="button" aria-label={`切换到${theme === "dark" ? "浅色" : "深色"}主题`} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "浅色" : "深色"}</button>
          <button type="button" onClick={() => void window.lionDesktop.disconnect()}>切换工作区</button>
          <span>Recent tokens: {formatTokens((snapshot.status?.input_tokens ?? 0) + (snapshot.status?.output_tokens ?? 0))}</span>
        </footer>
      </aside>
      <ChatThread
        workspaceName={workspaceName}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        onOpenSettings={() => setSettingsOpen(true)}
        skillPrompt={skillPrompt}
      />
      {settingsOpen ? <ProviderSettings onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  );
}

function ProviderSettings({ onClose }: { onClose: () => void }) {
  const { adapter, snapshot } = useLionRuntime();
  const status = snapshot.status;
  const providerName = status?.provider_name === "openai-compatible" ? "openai" : "anthropic";
  const [provider, setProvider] = useState<"openai" | "anthropic">(providerName);
  const [model, setModel] = useState(status?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    const saved = await adapter.configureProvider({
      provider,
      model,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
    });
    setSaving(false);
    if (saved) onClose();
  };

  return (
    <dialog className="settings-panel" open aria-labelledby="settings-title" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <form onSubmit={(event) => void save(event)}>
        <header><div><span className="workspace-kicker">运行配置</span><h2 id="settings-title">Provider 与模型</h2></div><button className="icon-button" type="button" aria-label="关闭设置" onClick={onClose}>×</button></header>
        {snapshot.metadataError ? <p className="form-error" role="alert">{snapshot.metadataError}</p> : null}
        <label>Provider<select value={provider} onChange={(event) => setProvider(event.target.value as "openai" | "anthropic")}><option value="anthropic">Anthropic</option><option value="openai">OpenAI compatible</option></select></label>
        <label>模型<select value={model} onChange={(event) => setModel(event.target.value)}>{snapshot.models.map((choice) => <option key={`${choice.provider_name}:${choice.model}`} value={choice.model}>{choice.model}</option>)}</select></label>
        <label>API key<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={status?.api_configured ? "已配置；留空保持不变" : "输入 API key"} /></label>
        <label>API 地址<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={provider === "openai" ? "https://api.openai.com/v1" : "可选自定义地址"} /></label>
        <label>Thinking<select value={status?.thinking_level ?? "off"} onChange={(event) => void adapter.setThinkingLevel(event.target.value)}>{status?.available_thinking_levels.map((level) => <option key={level}>{level}</option>)}</select></label>
        <footer><button type="button" className="button-quiet" onClick={onClose}>保留当前配置</button><button type="submit" disabled={saving || snapshot.protocol.isStreaming}>{saving ? "正在保存…" : "保存配置"}</button></footer>
      </form>
    </dialog>
  );
}

export function formatRelativeTime(value: string | null, now = Date.now()): string {
  if (!value) return "时间未知";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "时间未知";
  const elapsed = Math.max(0, now - timestamp);
  if (elapsed < 60_000) return "刚刚";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  if (elapsed < 604_800_000) return `${Math.floor(elapsed / 86_400_000)} 天前`;
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(timestamp);
}

function preferredTheme(): Theme {
  const stored = localStorage.getItem("lion-theme");
  if (stored === "light" || stored === "dark") return stored;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function formatTokens(tokens: number): string {
  return tokens < 1_000 ? String(tokens) : `${(tokens / 1_000).toFixed(tokens < 10_000 ? 1 : 0)}k`;
}
