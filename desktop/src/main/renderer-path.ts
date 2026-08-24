/** 自定义协议路径解析；与 Electron API 解耦以便契约测试。 */

import { relative, resolve, sep } from "node:path";

export function resolveRendererPath(rendererRoot: string, requestUrl: string): string {
  const url = new URL(requestUrl);
  if (url.protocol !== "lion:" || url.hostname !== "app") throw new Error("非法 Renderer URL");
  const decoded = decodeURIComponent(url.pathname);
  const requested = decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
  const root = resolve(rendererRoot);
  const candidate = resolve(root, requested);
  const child = relative(root, candidate);
  if (child === "" || child === "index.html") return candidate;
  if (child.startsWith(`..${sep}`) || child === ".." || resolve(root, child) !== candidate) {
    throw new Error("Renderer 路径越界");
  }
  return candidate;
}

export function resolveDevProxyUrl(
  rendererRoot: string,
  requestUrl: string,
  devServerUrl: string,
): string {
  const filePath = resolveRendererPath(rendererRoot, requestUrl);
  const requested = relative(resolve(rendererRoot), filePath).split(sep).join("/");
  const devRoot = new URL(devServerUrl);
  const target = new URL(requested, devRoot);
  if (target.origin !== devRoot.origin) throw new Error("开发代理目标越界");
  return target.href;
}
