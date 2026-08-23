/** Lion Electron Main：窗口、IPC 与单 sidecar 生命周期的 composition root。 */

import { existsSync } from "node:fs";
import { join } from "node:path";

import { app, protocol } from "electron";

import { registerDesktopIpc } from "./ipc";
import { registerLionProtocol } from "./protocol";
import { SidecarController } from "./sidecar";
import { WindowController } from "./window";
import { WorkspaceController } from "./workspace";

protocol.registerSchemesAsPrivileged([
  {
    scheme: "lion",
    privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, codeCache: true },
  },
]);

const sidecar = new SidecarController();
let windowController: WindowController;
let unregisterIpc: (() => void) | null = null;

function resolveSidecarCommand():
  | { ok: true; command: string; args: string[] }
  | { ok: false; message: string } {
  if (app.isPackaged) {
    const command = join(process.resourcesPath, "sidecar", "lion-sidecar.exe");
    return existsSync(command)
      ? { ok: true, command, args: [] }
      : { ok: false, message: "安装包缺少 Python sidecar 资源" };
  }
  return { ok: true, command: process.env.LION_PYTHON ?? "python", args: ["-m", "lion_code.sidecar"] };
}

app.whenReady().then(() => {
  registerLionProtocol(join(__dirname, "../renderer"), process.env.ELECTRON_RENDERER_URL);
  windowController = new WindowController({ preloadPath: join(__dirname, "../preload/index.cjs") });
  const workspaces = new WorkspaceController(join(app.getPath("userData"), "recent-workspaces.json"));
  unregisterIpc = registerDesktopIpc({
    getWindow: () => windowController.get(), sidecar, workspaces, resolveSidecarCommand,
  });
  windowController.create();
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (sidecar.getState().phase === "idle") return;
  event.preventDefault();
  unregisterIpc?.();
  unregisterIpc = null;
  void sidecar.stop().finally(() => {
    sidecar.resetToIdle();
    app.quit();
  });
});
