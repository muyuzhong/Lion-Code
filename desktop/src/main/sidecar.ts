/** Python sidecar 子进程生命周期：启动、ready 协议、退出与有界关闭。 */

import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";

import type { BackendEndpoint, BootstrapState } from "../shared/types";
import { failureFrom, parseReadyLine, sanitizeDiagnosticText, tailText } from "./ready";

export type SpawnFn = (command: string, args: string[]) => ChildProcess;

export interface SidecarControllerOptions {
  spawnFn?: SpawnFn;
  /** ready 记录等待上限；Python 首次冷启动较慢，默认 60s。 */
  readyTimeoutMs?: number;
  /** stderr 诊断尾部保留长度。 */
  stderrTailChars?: number;
}

const DEFAULT_READY_TIMEOUT_MS = 60_000;
const DEFAULT_STDERR_TAIL_CHARS = 4000;

/**
 * 单 sidecar 句柄的所有者。
 * 状态由 idle 单向迁移：starting → ready | failed；ready → exited。
 * capability 只存在于本实例内存与推送的 ready/exited 状态中。
 */
export class SidecarController {
  private state: BootstrapState = { phase: "idle" };
  private child: ChildProcess | null = null;
  private readonly listeners = new Set<(state: BootstrapState) => void>();
  private readonly spawnFn: SpawnFn;
  private readonly readyTimeoutMs: number;
  private readonly stderrTailChars: number;
  private stdoutBuffer = "";
  private stderrBuffer = "";
  private readySeen = false;
  private knownSecrets: string[] = [];
  private readyTimer: NodeJS.Timeout | null = null;
  private exitWaiters: Array<() => void> = [];

  constructor(options: SidecarControllerOptions = {}) {
    this.spawnFn = options.spawnFn ?? ((command, args) => spawn(command, args));
    this.readyTimeoutMs = options.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS;
    this.stderrTailChars = options.stderrTailChars ?? DEFAULT_STDERR_TAIL_CHARS;
  }

  getState(): BootstrapState {
    return this.state;
  }

  onChange(listener: (state: BootstrapState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** ready 态返回 endpoint，其余返回 null；capability 不写日志。 */
  getEndpoint(): BackendEndpoint | null {
    return this.state.phase === "ready" ? this.state.endpoint : null;
  }

  async start(workspacePath: string, command: string, args: string[]): Promise<void> {
    if (this.child !== null) {
      await this.stop();
    }
    this.reset();
    this.transition({ phase: "starting", workspacePath });

    let child: ChildProcess;
    try {
      child = this.spawnFn(command, args);
    } catch (error) {
      this.transition({
        phase: "failed",
        workspacePath,
        failure: failureFrom("spawn_failed", `无法启动 sidecar: ${errorMessage(error)}`),
      });
      return;
    }
    this.child = child;

    child.on("error", (error) => {
      // spawn 失败（如可执行文件缺失）通过 error 事件到达。
      if (this.state.phase === "starting") {
        this.clearReadyTimer();
        this.transition({
          phase: "failed",
          workspacePath,
          failure: failureFrom(
            "spawn_failed",
            `sidecar 启动失败: ${errorMessage(error)}`,
            this.sanitizedStderrTail(),
          ),
        });
      }
    });
    child.on("exit", (code, signal) => {
      this.clearReadyTimer();
      this.resolveExitWaiters();
      if (this.state.phase === "starting") {
        this.transition({
          phase: "failed",
          workspacePath,
          failure: failureFrom(
            "sidecar_exited",
            `sidecar 在就绪前退出（code=${code ?? "null"} signal=${signal ?? "null"}）`,
            this.sanitizedStderrTail(),
          ),
        });
      } else if (this.state.phase === "ready") {
        this.transition({
          phase: "exited",
          workspacePath: this.state.workspacePath,
          failure: failureFrom(
            "sidecar_exited",
            `sidecar 已退出（code=${code ?? "null"} signal=${signal ?? "null"}）`,
            this.sanitizedStderrTail(),
          ),
        });
      }
    });

    if (child.stdout !== null) {
      child.stdout.setEncoding("utf-8");
      child.stdout.on("data", (chunk: string) => this.handleStdout(chunk, workspacePath));
    }
    if (child.stderr !== null) {
      child.stderr.setEncoding("utf-8");
      child.stderr.on("data", (chunk: string) => {
        this.stderrBuffer = tailText(this.stderrBuffer + chunk, this.stderrTailChars);
      });
    }

    this.readyTimer = setTimeout(() => {
      if (this.state.phase === "starting") {
        void this.killChild();
        this.transition({
          phase: "failed",
          workspacePath,
          failure: failureFrom(
            "ready_timeout",
            `sidecar ${this.readyTimeoutMs}ms 内未输出 ready 记录`,
            this.sanitizedStderrTail(),
          ),
        });
      }
    }, this.readyTimeoutMs);
  }

  /**
   * 有界关闭：先请求终止，超时后强杀；始终针对本实例创建的确切子进程。
   * resolve 时子进程已退出（或从未启动）。
   */
  async stop(graceTimeoutMs = 5000): Promise<void> {
    this.clearReadyTimer();
    const child = this.child;
    if (child === null) {
      return;
    }
    const exited = this.waitForExit();
    this.killChild();
    const timeout = setTimeout(() => {
      this.killChild("SIGKILL");
    }, graceTimeoutMs);
    await exited;
    clearTimeout(timeout);
  }

  private waitForExit(): Promise<void> {
    if (this.child === null || this.child.exitCode !== null || this.child.signalCode !== null) {
      return Promise.resolve();
    }
    return new Promise<void>((resolve) => {
      this.exitWaiters.push(resolve);
    });
  }

  private resolveExitWaiters(): void {
    const waiters = this.exitWaiters;
    this.exitWaiters = [];
    for (const resolve of waiters) {
      resolve();
    }
  }

  private killChild(signal: NodeJS.Signals = "SIGTERM"): void {
    if (this.child !== null && this.child.exitCode === null && this.child.signalCode === null) {
      this.child.kill(signal);
    }
  }

  private handleStdout(chunk: string, workspacePath: string): void {
    this.stdoutBuffer += chunk;
    let newlineIndex = this.stdoutBuffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = this.stdoutBuffer.slice(0, newlineIndex);
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);
      this.handleProtocolLine(line, workspacePath);
      newlineIndex = this.stdoutBuffer.indexOf("\n");
    }
  }

  private handleProtocolLine(line: string, workspacePath: string): void {
    if (!line.trim()) {
      return;
    }
    if (this.readySeen) {
      // ready 之后 stdout 不再承载协议；重复 ready 是协议违规。
      if (parseReadyLine(line).ok) {
        this.failAfterReady(workspacePath, "duplicate_ready", "sidecar 输出了重复的 ready 记录");
      }
      return;
    }
    const result = parseReadyLine(line);
    if (!result.ok) {
      this.clearReadyTimer();
      void this.killChild();
      this.transition({
        phase: "failed",
        workspacePath,
        failure: failureFrom(
          "invalid_ready",
          `sidecar ready 记录非法: ${result.reason}`,
          this.sanitizedStderrTail(),
        ),
      });
      return;
    }
    const { port, capability } = result.record;
    this.knownSecrets.push(capability);
    this.readySeen = true;
    this.clearReadyTimer();
    this.transition({
      phase: "ready",
      workspacePath,
      endpoint: {
        baseUrl: `http://127.0.0.1:${port}`,
        capability,
      },
    });
  }

  private failAfterReady(workspacePath: string, code: "duplicate_ready", message: string): void {
    void this.killChild();
    this.transition({
      phase: "failed",
      workspacePath,
      failure: failureFrom(code, message, this.sanitizedStderrTail()),
    });
  }

  private sanitizedStderrTail(): string | undefined {
    if (!this.stderrBuffer.trim()) {
      return undefined;
    }
    return tailText(
      sanitizeDiagnosticText(this.stderrBuffer, this.knownSecrets),
      this.stderrTailChars,
    );
  }

  private reset(): void {
    this.stdoutBuffer = "";
    this.stderrBuffer = "";
    this.readySeen = false;
    this.knownSecrets = [];
    this.clearReadyTimer();
  }

  private clearReadyTimer(): void {
    if (this.readyTimer !== null) {
      clearTimeout(this.readyTimer);
      this.readyTimer = null;
    }
  }

  private transition(next: BootstrapState): void {
    this.state = next;
    for (const listener of this.listeners) {
      listener(next);
    }
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

