import type { DesktopBridge } from "../../shared/types";

declare global {
  interface Window { lionDesktop: DesktopBridge; }
}

export {};
