/** lion://app 资源协议：只允许读取 Renderer 根目录内的文件。 */

import { readFile } from "node:fs/promises";
import { extname } from "node:path";

import { net, protocol } from "electron";
import { resolveDevProxyUrl, resolveRendererPath } from "./renderer-path";

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' lion:",
  "style-src 'self' lion: 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
].join("; ");

// dev 模式下 lion:// 页面由 vite dev server 代理：HMR websocket 按协议相对
// 解析为 ws://app/...，@vitejs/plugin-react 的 preamble 以内联 script 注入。
// 生产模式走文件协议不涉及，故仅在 dev 放宽这两项。
const DEV_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace(
  "script-src 'self' lion:",
  "script-src 'self' lion: 'unsafe-inline'",
).replace(
  "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*",
  "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:* ws://app:*",
);

const MIME_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

export function registerLionProtocol(rendererRoot: string, devServerUrl?: string): void {
  protocol.handle("lion", async (request) => {
    try {
      if (devServerUrl) {
        const response = await net.fetch(resolveDevProxyUrl(rendererRoot, request.url, devServerUrl));
        const headers = new Headers(response.headers);
        headers.set("Content-Security-Policy", DEV_CONTENT_SECURITY_POLICY);
        return new Response(response.body, { status: response.status, headers });
      }
      const filePath = resolveRendererPath(rendererRoot, request.url);
      const body = await readFile(filePath);
      return new Response(body, {
        status: 200,
        headers: {
          "Content-Type": MIME_TYPES[extname(filePath).toLowerCase()] ?? "application/octet-stream",
          "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        },
      });
    } catch {
      return new Response("Not found", { status: 404 });
    }
  });
}
