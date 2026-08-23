/** BrowserWindow 的可测试安全配置。 */

import type { WebPreferences } from "electron";

export function secureWebPreferences(preloadPath: string): WebPreferences {
  return { preload: preloadPath, nodeIntegration: false, contextIsolation: true, sandbox: true };
}

export function isTrustedRendererUrl(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl);
    return url.protocol === "lion:" && url.hostname === "app";
  } catch {
    return false;
  }
}
