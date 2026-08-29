/** Main / Preload / Renderer 三端共享的桌面契约类型。 */

/** sidecar 经 stdout 交付的唯一 ready 记录（严格 schema，见 parseReadyLine）。 */
export interface SidecarReadyRecord {
  type: "ready";
  version: number;
  port: number;
  capability: string;
}

export interface BackendEndpoint {
  /** REST/WS 根地址，形如 http://127.0.0.1:49152 */
  baseUrl: string;
  /** 本机 capability；仅存在于 Main 内存与 Renderer 运行时状态，禁止持久化。 */
  capability: string;
}

export type BootstrapErrorCode =
  | "spawn_failed"
  | "ready_timeout"
  | "invalid_ready"
  | "duplicate_ready"
  | "sidecar_exited"
  | "sidecar_assets_missing"
  | "workspace_invalid"
  | "unknown";

export interface BootstrapFailure {
  code: BootstrapErrorCode;
  /** 安全诊断信息：不含 capability，不含原始 stderr。 */
  message: string;
  /** 已净化的 stderr 尾部，仅诊断视图展示。 */
  stderrTail?: string;
}

/** Renderer bootstrap 判别联合；由 Main 拥有并推送。 */
export type BootstrapState =
  | { phase: "idle" }
  | { phase: "starting"; workspacePath: string }
  | { phase: "ready"; workspacePath: string; endpoint: BackendEndpoint }
  | { phase: "failed"; workspacePath: string; failure: BootstrapFailure }
  | { phase: "exited"; workspacePath: string; failure: BootstrapFailure };

/**
 * Preload 暴露给 Renderer 的最小能力面。
 * 固定 channel、固定参数 schema；不含 ipcRenderer、文件系统或进程执行。
 */
export interface DesktopBridge {
  getBootstrapState(): Promise<BootstrapState>;
  onBootstrapStateChange(listener: (state: BootstrapState) => void): () => void;
  selectWorkspace(): Promise<string | null>;
  getRecentWorkspaces(): Promise<string[]>;
  connectWorkspace(path: string): Promise<void>;
  disconnect(): Promise<void>;
}

/** Main → Renderer 状态推送 channel（preload 内部使用，不暴露给页面）。 */
export const BOOTSTRAP_STATE_CHANNEL = "desktop:bootstrap-state-changed";
