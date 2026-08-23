import { PassThrough } from "node:stream";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import { describe, expect, it, vi } from "vitest";
import { SidecarController } from "../src/main/sidecar";

function fakeChild() {
  const child = new EventEmitter() as EventEmitter & Partial<ChildProcess>;
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  Object.defineProperty(child, "exitCode", { value: null, writable: true });
  Object.defineProperty(child, "signalCode", { value: null, writable: true });
  child.kill = vi.fn((signal?: NodeJS.Signals) => {
    Reflect.set(child, "signalCode", signal ?? "SIGTERM");
    queueMicrotask(() => child.emit("exit", null, child.signalCode));
    return true;
  });
  return child as ChildProcess;
}

describe("SidecarController", () => {
  it("moves to ready and rejects a duplicate ready record", async () => {
    const child = fakeChild();
    const controller = new SidecarController({ spawnFn: () => child, readyTimeoutMs: 1000 });
    await controller.start("C:\\workspace", "python", []);
    const ready = JSON.stringify({ type: "ready", version: 1, port: 43123, capability: "a".repeat(32) });
    child.stdout!.emit("data", `${ready}\n`);
    expect(controller.getState().phase).toBe("ready");
    child.stdout!.emit("data", `${ready}\n`);
    expect(controller.getState()).toMatchObject({ phase: "failed", failure: { code: "duplicate_ready" } });
  });

  it("redacts capability from stderr on unexpected exit", async () => {
    const child = fakeChild();
    const controller = new SidecarController({ spawnFn: () => child });
    await controller.start("C:\\workspace", "python", []);
    const secret = "s".repeat(32);
    child.stdout!.emit("data", `${JSON.stringify({ type: "ready", version: 1, port: 43123, capability: secret })}\n`);
    child.stderr!.emit("data", `failure ${secret}`);
    child.emit("exit", 1, null);
    expect(controller.getState()).toMatchObject({
      phase: "exited", failure: { code: "sidecar_exited", stderrTail: "failure [REDACTED]" },
    });
  });

  it("terminates the exact owned process", async () => {
    const child = fakeChild();
    const controller = new SidecarController({ spawnFn: () => child });
    await controller.start("C:\\workspace", "python", []);
    await controller.stop(20);
    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
  });

  it("serializes concurrent workspace switches without orphaning a process", async () => {
    const children = [fakeChild(), fakeChild(), fakeChild()];
    let spawnIndex = 0;
    const controller = new SidecarController({ spawnFn: () => children[spawnIndex++]! });
    await controller.start("C:\\first", "python", []);

    await Promise.all([
      controller.start("C:\\second", "python", []),
      controller.start("C:\\third", "python", []),
    ]);

    expect(children[0]!.kill).toHaveBeenCalled();
    expect(children[1]!.kill).toHaveBeenCalled();
    expect(children[2]!.kill).not.toHaveBeenCalled();
    expect(controller.getState()).toMatchObject({ phase: "starting", workspacePath: "C:\\third" });
  });

  it("redacts a capability that crosses the diagnostic tail boundary", async () => {
    const child = fakeChild();
    const controller = new SidecarController({ spawnFn: () => child, stderrTailChars: 20 });
    await controller.start("C:\\workspace", "python", []);
    const secret = "s".repeat(32);
    child.stdout!.emit("data", `${JSON.stringify({ type: "ready", version: 1, port: 43123, capability: secret })}\n`);
    child.stderr!.emit("data", `prefix-${secret}${"z".repeat(10)}`);
    child.emit("exit", 1, null);
    const state = controller.getState();
    expect(state.phase).toBe("exited");
    if (state.phase === "exited") expect(state.failure.stderrTail).not.toContain("ssss");
  });

  it("serializes a pre-spawn failure and reaps the existing child", async () => {
    const child = fakeChild();
    const controller = new SidecarController({ spawnFn: () => child });
    await controller.start("C:\\workspace", "python", []);
    await controller.setFailure("relative", "workspace_invalid", "invalid");

    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
    expect(controller.getState()).toMatchObject({ phase: "failed", failure: { code: "workspace_invalid" } });
  });
});
