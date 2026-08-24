/** Electron 窗口的安全配置与外部导航策略。 */

import { BrowserWindow, session, shell } from "electron";
import { isTrustedRendererUrl, secureWebPreferences } from "./window-security";

const ALLOWED_EXTERNAL_ORIGINS = new Set<string>();

export interface WindowControllerOptions {
  preloadPath: string;
}

export class WindowController {
  private window: BrowserWindow | null = null;

  constructor(private readonly options: WindowControllerOptions) {}

  create(): BrowserWindow {
    const window = new BrowserWindow({
      width: 1120,
      height: 760,
      minWidth: 720,
      minHeight: 520,
      show: false,
      webPreferences: secureWebPreferences(this.options.preloadPath),
    });
    this.window = window;
    window.once("ready-to-show", () => window.show());
    window.webContents.on("will-navigate", (event, url) => {
      if (!isTrustedRendererUrl(url)) {
        event.preventDefault();
      }
    });
    window.webContents.setWindowOpenHandler(({ url }) => {
      void openAllowedExternal(url);
      return { action: "deny" };
    });
    session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
      callback(false);
    });
    void window.loadURL("lion://app/");
    window.on("closed", () => {
      if (this.window === window) this.window = null;
    });
    return window;
  }

  get(): BrowserWindow | null {
    return this.window;
  }
}

async function openAllowedExternal(rawUrl: string): Promise<void> {
  try {
    const url = new URL(rawUrl);
    if (url.protocol === "https:" && ALLOWED_EXTERNAL_ORIGINS.has(url.origin)) {
      await shell.openExternal(url.href);
    }
  } catch {
    // 非法 URL 与非 allowlist URL 一律拒绝。
  }
}
