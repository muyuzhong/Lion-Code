import { describe, expect, it, vi } from "vitest";
import { createDesktopBridge, type PreloadIpcPort } from "../src/preload/bridge";

describe("preload bridge", () => {
  it("maps only the declared desktop channels and removes listeners", async () => {
    const invoke = vi.fn(async () => null);
    const on = vi.fn();
    const removeListener = vi.fn();
    const bridge = createDesktopBridge({ invoke, on, removeListener } satisfies PreloadIpcPort);

    await bridge.connectWorkspace("C:\\workspace");
    const unsubscribe = bridge.onBootstrapStateChange(() => undefined);
    unsubscribe();

    expect(invoke).toHaveBeenNthCalledWith(1, "desktop:connect-workspace", "C:\\workspace");
    expect(on).toHaveBeenCalledWith("desktop:bootstrap-state-changed", expect.any(Function));
    expect(removeListener).toHaveBeenCalledWith("desktop:bootstrap-state-changed", expect.any(Function));
    expect(Object.keys(bridge).sort()).toEqual([
      "connectWorkspace", "disconnect", "getBootstrapState",
      "getRecentWorkspaces", "onBootstrapStateChange", "selectWorkspace",
    ]);
  });
});
