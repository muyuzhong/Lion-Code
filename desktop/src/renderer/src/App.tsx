import { useEffect, useState } from "react";
import type { BootstrapState } from "../../shared/types";
import { WorkspaceShell } from "./WorkspaceShell";

export function App() {
  const [state, setState] = useState<BootstrapState>({ phase: "idle" });
  const [recent, setRecent] = useState<string[]>([]);
  useEffect(() => {
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

  return <main className="boot-shell">
    <section className="boot-copy">
      <div className="brand-lockup boot-brand"><span className="brand-mark" aria-hidden="true">L</span><div><strong>Lion</strong><small>desktop agent</small></div></div>
      <p className="eyebrow">WINDOWS WORKSPACE</p>
      <h1>{headline(state)}</h1>
      <p className="detail">{detail(state)}</p>
      <div className="actions">
        <button onClick={() => void choose()} disabled={state.phase === "starting"}>{state.phase === "idle" ? "选择工作区" : "选择其他工作区"}</button>
        {state.phase !== "idle" ? <button className="button-quiet" onClick={() => void window.lionDesktop.disconnect()}>停止连接</button> : null}
      </div>
    </section>
    <section className="boot-activity" aria-live="polite">
      <span className={`boot-orbit ${state.phase}`} aria-hidden="true"><i /><i /><i /></span>
      <div><span className="workspace-kicker">连接状态</span><strong>{state.phase === "starting" ? "正在创建本机安全会话" : headline(state)}</strong></div>
      {state.phase === "failed" || state.phase === "exited" ? <pre>{state.failure.stderrTail ?? state.failure.message}</pre> : null}
    </section>
    {recent.length > 0 && state.phase === "idle" ? <section className="recent-workspaces"><h2>最近打开</h2>{recent.map((path) => <button className="recent" key={path} onClick={() => void connect(path)}><span>{path.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1)}</span><small>{path}</small></button>)}</section> : null}
  </main>;
}

function headline(state: BootstrapState): string {
  return ({ idle: "选择一个工作区", starting: "正在启动 Lion…", ready: "Lion 已连接", failed: "启动失败", exited: "连接已断开" })[state.phase];
}

function detail(state: BootstrapState): string {
  if (state.phase === "idle") return "桌面宿主会为当前工作区启动一个本机 sidecar。";
  if (state.phase === "starting") return state.workspacePath;
  if (state.phase === "ready") return state.workspacePath;
  return state.failure.message;
}
