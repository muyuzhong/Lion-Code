import { defineConfig } from "@playwright/test";

// bootstrap：fake sidecar 驱动的宿主/E2E 契约（默认运行）。
// sidecar-real：真实 Python sidecar 的开发态链路（显式指定时运行）。
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    trace: "off",
  },
  projects: [
    {
      name: "bootstrap",
      testMatch: /bootstrap.*\.spec\.ts/,
    },
    {
      name: "sidecar-real",
      testMatch: /sidecar-real\.spec\.ts/,
    },
  ],
});
