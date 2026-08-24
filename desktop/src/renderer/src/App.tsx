import { FolderOpen, LoaderCircle, PanelLeft, Search, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import type { BootstrapState } from "../../shared/types";
import { WorkspaceShell } from "./WorkspaceShell";

export function App() {
  const [state, setState] = useState<BootstrapState>({ phase: "idle" });
  const [recent, setRecent] = useState<string[]>([]);
  useEffect(() => {
    document.documentElement.dataset.theme = "dark";
    void window.lionDesktop.getBootstrapState().then(setState);
    void window.lionDesktop.getRecentWorkspaces().then(setRecent);
    return window.lionDesktop.onBootstrapStateChange(setState);
  }, []);

  const choose = async () => {
    const path = await window.lionDesktop.selectWorkspace();
    if (path) await window.lionDesktop.connectWorkspace(path);
  };
  const connect = async (path: string) => window.lionDesktop.connectWorkspace(path);

  if (state.phase === "ready") return <WorkspaceShell endpoint={state.endpoint} workspacePath={state.workspacePath} />;

  return (
    <main className="boot-shell">
      <aside className="boot-sidebar">
        <header><strong>Lion</strong><div><Search aria-hidden="true" size={16} /><PanelLeft aria-hidden="true" size={16} /></div></header>
        <span className="boot-section-label">最近打开</span>
        <div className="recent-workspaces">
          {recent.map((path) => <button className="recent" key={path} onClick={() => void connect(path)}><FolderOpen aria-hidden="true" size={15} /><span><strong>{path.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1)}</strong><small>{path}</small></span></button>)}
          {recent.length === 0 ? <p>还没有最近工作区。</p> : null}
        </div>
        <footer><Settings aria-hidden="true" size={16} /><span>v1.0.0</span></footer>
      </aside>
      <section className="boot-main">
        <div className="boot-content">
          <span className="boot-icon">{state.phase === "starting" ? <LoaderCircle className="spin" aria-hidden="true" size={22} /> : <FolderOpen aria-hidden="true" size={22} />}</span>
          <h1>{headline(state)}</h1>
          <p>{detail(state)}</p>
          <div className="boot-actions"><button type="button" onClick={() => void choose()} disabled={state.phase === "starting"}>{state.phase === "idle" ? "打开工作区" : "选择其他工作区"}</button>{state.phase !== "idle" ? <button type="button" className="button-quiet" onClick={() => void window.lionDesktop.disconnect()}>停止连接</button> : null}</div>
          {state.phase === "failed" || state.phase === "exited" ? <pre>{state.failure.stderrTail ?? state.failure.message}</pre> : null}
        </div>
      </section>
    </main>
  );
}

function headline(state: BootstrapState): string {
  return ({ idle: "选择一个工作区", starting: "正在启动 Lion", ready: "Lion 已连接", failed: "启动失败", exited: "连接已断开" })[state.phase];
}

function detail(state: BootstrapState): string {
  if (state.phase === "idle") return "选择本地项目，Lion 会在该工作区启动安全的 sidecar。";
  if (state.phase === "starting" || state.phase === "ready") return state.workspacePath;
  return state.failure.message;
}
