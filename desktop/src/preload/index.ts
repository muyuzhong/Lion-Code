/** Renderer 的唯一原生能力入口；不暴露 ipcRenderer 本体。 */

import { contextBridge, ipcRenderer } from "electron";

import { createDesktopBridge } from "./bridge";

const bridge = createDesktopBridge(ipcRenderer);

contextBridge.exposeInMainWorld("lionDesktop", bridge);
