import { useEffect, useState } from "react";
import type { BootstrapState } from "../../shared/types";

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

  return <main>
    <p className="eyebrow">LION DESKTOP</p>
    <h1>{headline(state)}</h1>
    <p className="detail">{detail(state)}</p>
    {state.phase === "failed" || state.phase === "exited" ? <pre>{state.failure.stderrTail ?? state.failure.message}</pre> : null}
    <div className="actions">
      <button onClick={() => void choose()} disabled={state.phase === "starting"}>选择工作区</button>
      {state.phase !== "idle" ? <button className="secondary" onClick={() => void window.lionDesktop.disconnect()}>断开</button> : null}
    </div>
    {recent.length > 0 && state.phase === "idle" ? <section><h2>最近工作区</h2>{recent.map((path) => <button className="recent" key={path} onClick={() => void connect(path)}>{path}</button>)}</section> : null}
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
