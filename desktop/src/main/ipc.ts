/** 固定 IPC allowlist；每次调用都校验 sender 与当前窗口身份。 */

import { dialog, ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from "electron";

import { BOOTSTRAP_STATE_CHANNEL } from "../shared/types";
import { isTrustedIpcSender } from "./ipc-contract";
import type { SidecarController } from "./sidecar";
import type { WorkspaceController } from "./workspace";

export interface DesktopIpcDependencies {
  getWindow(): BrowserWindow | null;
  sidecar: SidecarController;
  workspaces: WorkspaceController;
  resolveSidecarCommand():
    | { ok: true; command: string; args: string[] }
    | { ok: false; message: string };
}

export function registerDesktopIpc(deps: DesktopIpcDependencies): () => void {
  const assertSender = (event: IpcMainInvokeEvent): void => {
    const window = deps.getWindow();
    if (!isTrustedIpcSender(
      event.senderFrame?.url ?? null,
      event.sender.id,
      window?.webContents.id ?? null,
    )) {
      throw new Error("拒绝非受信 Renderer IPC");
    }
  };
  const handle = (channel: string, listener: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown) => {
    ipcMain.handle(channel, (event, ...args) => {
      assertSender(event);
      return listener(event, ...args);
    });
  };

  handle("desktop:get-bootstrap-state", () => deps.sidecar.getState());
  handle("desktop:get-recent-workspaces", () => deps.workspaces.listRecent());
  handle("desktop:select-workspace", async () => {
    const window = deps.getWindow();
    if (window === null) return null;
    const result = await dialog.showOpenDialog(window, { properties: ["openDirectory"] });
    return result.canceled ? null : result.filePaths[0] ?? null;
  });
  handle("desktop:connect-workspace", async (_event, rawPath) => {
    const candidate = typeof rawPath === "string" ? rawPath : "";
    let workspacePath: string;
    try {
      workspacePath = await deps.workspaces.validate(candidate);
    } catch {
      await deps.sidecar.setFailure(candidate, "workspace_invalid", "workspace 必须是可访问的绝对目录");
      return;
    }
    await deps.workspaces.remember(workspacePath);
    const sidecar = deps.resolveSidecarCommand();
    if (!sidecar.ok) {
      await deps.sidecar.setFailure(workspacePath, "sidecar_assets_missing", sidecar.message);
      return;
    }
    await deps.sidecar.start(workspacePath, sidecar.command, [...sidecar.args, "--workspace", workspacePath]);
  });
  handle("desktop:disconnect", () => deps.sidecar.stop());

  const unsubscribe = deps.sidecar.onChange((state) => {
    deps.getWindow()?.webContents.send(BOOTSTRAP_STATE_CHANNEL, state);
  });
  const channels = [
    "desktop:get-bootstrap-state", "desktop:get-recent-workspaces",
    "desktop:select-workspace", "desktop:connect-workspace", "desktop:disconnect",
  ];
  return () => {
    unsubscribe();
    for (const channel of channels) ipcMain.removeHandler(channel);
  };
}
