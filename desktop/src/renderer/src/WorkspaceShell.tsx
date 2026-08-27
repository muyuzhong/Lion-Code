import { Eye, EyeOff, Settings2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type PointerEvent as ReactPointerEvent } from "react";
import type { BackendEndpoint } from "../../shared/types";
import { LionRuntimeProvider, useLionRuntime } from "./assistantRuntime";
import { browserBackendBootstrap } from "./backend";
import { ChatThread } from "./ChatThread";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { WorkPanel } from "./components/WorkPanel";

type Theme = "light" | "dark";

export function WorkspaceShell({ endpoint, workspacePath }: { endpoint: BackendEndpoint; workspacePath: string }) {
  const bootstrap = useMemo(() => browserBackendBootstrap(endpoint), [endpoint.baseUrl, endpoint.capability]);
  return <LionRuntimeProvider bootstrap={bootstrap}><Workspace workspacePath={workspacePath} /></LionRuntimeProvider>;
}

function Workspace({ workspacePath }: { workspacePath: string }) {
  const { adapter, snapshot } = useLionRuntime();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [workPanelOpen, setWorkPanelOpen] = useState(true);
  const [sessionSearchOpen, setSessionSearchOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [skillPrompt, setSkillPrompt] = useState<{ key: number; text: string } | null>(null);
  const [theme, setTheme] = useState<Theme>(() => preferredTheme());
  const [sidebarWidth, setSidebarWidth] = useState(() => preferredPaneWidth("lion-sidebar-width", 275, 240, 520));
  const [workPanelWidth, setWorkPanelWidth] = useState(() => preferredPaneWidth("lion-work-panel-width", 320, 280, 640));
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const firstRunShown = useRef(false);
  const workspaceName = workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1) || workspacePath;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lion-theme", theme);
  }, [theme]);

  useEffect(() => localStorage.setItem("lion-sidebar-width", String(sidebarWidth)), [sidebarWidth]);
  useEffect(() => localStorage.setItem("lion-work-panel-width", String(workPanelWidth)), [workPanelWidth]);
  useEffect(() => {
    const updateViewportWidth = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", updateViewportWidth);
    return () => window.removeEventListener("resize", updateViewportWidth);
  }, []);

  useEffect(() => {
    if (snapshot.status?.api_configured === false && !firstRunShown.current) {
      firstRunShown.current = true;
      setSettingsOpen(true);
    }
  }, [snapshot.status?.api_configured]);

  const createSession = () => void adapter.createSession();
  const startPaneResize = (pane: "sidebar" | "work-panel", event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const controller = new AbortController();
    document.documentElement.dataset.paneResizing = pane;
    const move = (moveEvent: PointerEvent) => {
      if (pane === "sidebar") {
        setSidebarWidth(clampPaneWidth(moveEvent.clientX, 240, Math.min(520, window.innerWidth - workPanelWidth - 360)));
      } else {
        setWorkPanelWidth(clampPaneWidth(window.innerWidth - moveEvent.clientX, 280, Math.min(640, window.innerWidth - sidebarWidth - 360)));
      }
    };
    const finish = () => {
      controller.abort();
      delete document.documentElement.dataset.paneResizing;
    };
    window.addEventListener("pointermove", move, { signal: controller.signal });
    window.addEventListener("pointerup", finish, { once: true, signal: controller.signal });
    window.addEventListener("blur", finish, { once: true, signal: controller.signal });
  };
  const workPanelConsumesWidth = workPanelOpen && viewportWidth > 980;
  const renderedSidebarWidth = clampPaneWidth(sidebarWidth, 240, Math.min(520, viewportWidth - (workPanelConsumesWidth ? 280 : 0) - 360));
  const renderedWorkPanelWidth = clampPaneWidth(workPanelWidth, 280, Math.min(640, viewportWidth - renderedSidebarWidth - 360));
  const shellStyle = {
    "--ds-sidebar-width": `${renderedSidebarWidth}px`,
    "--work-panel-width": `${renderedWorkPanelWidth}px`,
  } as CSSProperties;
  return (
    <div className={`workspace-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`} style={shellStyle}>
      <a className="skip-link" href="#lion-thread">跳到对话</a>
      {!sidebarCollapsed ? <DesktopSidebar
        workspaceName={workspaceName}
        sessions={snapshot.sessions}
        activeSessionId={snapshot.status?.session_id}
        skills={snapshot.skills}
        isStreaming={snapshot.protocol.isStreaming}
        theme={theme}
        formatTime={formatRelativeTime}
        onCreateSession={createSession}
        onSwitchSession={(sessionId) => void adapter.switchSession(sessionId)}
        onRenameSession={(sessionId, label) => adapter.renameSession(sessionId, label)}
        onSelectSkill={(skillName) => setSkillPrompt({ key: Date.now(), text: `/${skillName} ` })}
        onOpenSettings={() => setSettingsOpen(true)}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        onDisconnect={() => void window.lionDesktop.disconnect()}
        onCollapse={() => setSidebarCollapsed(true)}
        searchOpen={sessionSearchOpen}
        onSearchOpenChange={setSessionSearchOpen}
        onResizeStart={(event) => startPaneResize("sidebar", event)}
        onResizeBy={(delta) => setSidebarWidth((width) => clampPaneWidth(width + delta, 240, Math.min(520, window.innerWidth - workPanelWidth - 360)))}
      /> : null}
      <section className="workspace-main">
        <ChatThread
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed(false)}
          onCreateSession={createSession}
          onOpenSearch={() => { setSidebarCollapsed(false); setSessionSearchOpen(true); }}
          onOpenSettings={() => setSettingsOpen(true)}
          skills={snapshot.skills}
          skillPrompt={skillPrompt}
        />
        {workPanelOpen ? <WorkPanel
          onClose={() => setWorkPanelOpen(false)}
          onResizeStart={(event) => startPaneResize("work-panel", event)}
          onResizeBy={(delta) => setWorkPanelWidth((width) => clampPaneWidth(width + delta, 280, Math.min(640, window.innerWidth - sidebarWidth - 360)))}
        /> : <button className="work-panel-return" type="button" aria-label="打开工作面板" onClick={() => setWorkPanelOpen(true)}><span>工作面板</span></button>}
      </section>
      {settingsOpen ? <ProviderSettings onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  );
}

export function ProviderSettings({ onClose }: { onClose: () => void }) {
  const { adapter, snapshot } = useLionRuntime();
  const status = snapshot.status;
  const providerName = status?.provider_name === "openai-compatible" ? "openai" : "anthropic";
  const [provider, setProvider] = useState<"openai" | "anthropic">(providerName);
  const [model, setModel] = useState(status?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [allowHosts, setAllowHosts] = useState("");
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [loadingConfiguration, setLoadingConfiguration] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    setApiKeyVisible(false);
    setLoadingConfiguration(true);
    void Promise.all([
      adapter.fetchProviderConfiguration().then((configuration) => {
        if (!mounted || !configuration) return;
        setProvider(configuration.provider);
        setModel(configuration.model);
        setApiKey(configuration.api_key);
        setBaseUrl(configuration.base_url);
      }),
      adapter.fetchEgressConfiguration().then((egress) => {
        if (!mounted || !egress) return;
        setAllowHosts(egress.allow_hosts.join("\n"));
      }),
    ]).finally(() => {
      if (mounted) setLoadingConfiguration(false);
    });
    return () => { mounted = false; };
  }, [adapter]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    const parsedHosts = allowHosts
      .split(/[\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    const [savedProvider, savedEgress] = await Promise.all([
      adapter.configureProvider({
        provider,
        model,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {})
      }),
      adapter.configureEgress({ allow_hosts: parsedHosts }),
    ]);
    setSaving(false);
    if (savedProvider && savedEgress) onClose();
  };

  return (
    <dialog className="settings-panel" open aria-labelledby="settings-title" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <form onSubmit={(event) => void save(event)}>
        <header><span className="settings-icon" aria-hidden="true"><Settings2 size={18} /></span><div><span className="workspace-kicker">运行配置</span><h2 id="settings-title">Provider 与模型</h2></div><button className="dialog-close" type="button" aria-label="关闭设置" onClick={onClose}><X aria-hidden="true" size={17} /></button></header>
        {snapshot.metadataError ? <p className="form-error" role="alert">{snapshot.metadataError}</p> : null}
        <label htmlFor="provider-select">Provider<select id="provider-select" value={provider} onChange={(event) => setProvider(event.target.value as "openai" | "anthropic")}><option value="anthropic">Anthropic</option><option value="openai">OpenAI compatible</option></select></label>
        <label htmlFor="model-select">模型<select id="model-select" value={model} onChange={(event) => setModel(event.target.value)}>{model && !snapshot.models.some((choice) => choice.model === model) ? <option value={model}>{model}</option> : null}{snapshot.models.map((choice) => <option key={`${choice.provider_name}:${choice.model}`} value={choice.model}>{choice.model}</option>)}</select></label>
        <label htmlFor="provider-api-key">API key<div style={{ position: "relative" }}><input id="provider-api-key" type={apiKeyVisible ? "text" : "password"} autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={loadingConfiguration ? "正在读取…" : status?.api_configured ? "已配置；留空保持不变" : "输入 API key"} style={{ paddingRight: 40 }} /><button type="button" aria-label={apiKeyVisible ? "隐藏 API key" : "显示 API key"} aria-pressed={apiKeyVisible} aria-controls="provider-api-key" onClick={() => setApiKeyVisible((visible) => !visible)} style={{ position: "absolute", top: "50%", right: 5, display: "inline-flex", width: 28, height: 28, alignItems: "center", justifyContent: "center", borderRadius: "var(--radius-xs)", color: "var(--ds-text-muted)", transform: "translateY(-50%)" }}>{apiKeyVisible ? <EyeOff aria-hidden="true" size={16} /> : <Eye aria-hidden="true" size={16} />}</button></div></label>
        <label htmlFor="provider-base-url">API 地址<input id="provider-base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={provider === "openai" ? "https://api.openai.com/v1" : "可选自定义地址"} /></label>
        <label htmlFor="egress-allow-hosts">网络出口白名单 (Web Fetch)<textarea id="egress-allow-hosts" value={allowHosts} onChange={(event) => setAllowHosts(event.target.value)} placeholder={loadingConfiguration ? "正在读取…" : "每行一个域名，例如：\napi.github.com\nraw.githubusercontent.com"} rows={3} /></label>
        <label>Thinking<select value={status?.thinking_level ?? "medium"} onChange={(event) => void adapter.setThinkingLevel(event.target.value)}>{status?.available_thinking_levels.map((level) => <option key={level}>{level}</option>)}</select></label>
        <footer><button type="button" className="button-quiet" onClick={onClose}>保留当前配置</button><button type="submit" disabled={saving || loadingConfiguration || snapshot.protocol.isStreaming}>{loadingConfiguration ? "正在读取…" : saving ? "正在保存…" : "保存配置"}</button></footer>
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
  return stored === "light" || stored === "dark" ? stored : "dark";
}

function preferredPaneWidth(key: string, fallback: number, minimum: number, maximum: number): number {
  const stored = Number(localStorage.getItem(key));
  return Number.isFinite(stored) && stored > 0 ? clampPaneWidth(stored, minimum, maximum) : fallback;
}

function clampPaneWidth(value: number, minimum: number, maximum: number): number {
  return Math.round(Math.min(Math.max(value, minimum), Math.max(minimum, maximum)));
}
