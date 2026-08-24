/** IPC sender 身份判断；与 Electron 对象解耦以便安全回归测试。 */

import { isTrustedRendererUrl } from "./window-security";

export function isTrustedIpcSender(
  frameUrl: string | null,
  senderWebContentsId: number,
  windowWebContentsId: number | null,
): boolean {
  return (
    frameUrl !== null &&
    windowWebContentsId !== null &&
    senderWebContentsId === windowWebContentsId &&
    isTrustedRendererUrl(frameUrl)
  );
}
