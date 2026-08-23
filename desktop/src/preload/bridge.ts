/** Preload allowlist 的纯构造函数；只接受固定 channel 的窄 IPC 端口。 */

import { BOOTSTRAP_STATE_CHANNEL, type BootstrapState, type DesktopBridge } from "../shared/types";

export interface PreloadIpcPort {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, listener: (event: unknown, state: BootstrapState) => void): void;
  removeListener(channel: string, listener: (event: unknown, state: BootstrapState) => void): void;
}

export function createDesktopBridge(ipc: PreloadIpcPort): DesktopBridge {
  return {
    getAppInfo: () => ipc.invoke("desktop:get-app-info") as ReturnType<DesktopBridge["getAppInfo"]>,
    getBootstrapState: () => ipc.invoke("desktop:get-bootstrap-state") as ReturnType<DesktopBridge["getBootstrapState"]>,
    getRecentWorkspaces: () => ipc.invoke("desktop:get-recent-workspaces") as ReturnType<DesktopBridge["getRecentWorkspaces"]>,
    selectWorkspace: () => ipc.invoke("desktop:select-workspace") as ReturnType<DesktopBridge["selectWorkspace"]>,
    connectWorkspace: (path) => ipc.invoke("desktop:connect-workspace", path) as Promise<void>,
    disconnect: () => ipc.invoke("desktop:disconnect") as Promise<void>,
    getBackendEndpoint: () => ipc.invoke("desktop:get-backend") as ReturnType<DesktopBridge["getBackendEndpoint"]>,
    onBootstrapStateChange(listener) {
      const handler = (_event: unknown, state: BootstrapState) => listener(state);
      ipc.on(BOOTSTRAP_STATE_CHANNEL, handler);
      return () => ipc.removeListener(BOOTSTRAP_STATE_CHANNEL, handler);
    },
  };
}
