import { defineConfig } from "@playwright/test";

const projects = [
  {
    name: "bootstrap",
    testMatch: /bootstrap.*\.spec\.ts/,
  },
  {
    name: "sidecar-real",
    testMatch: /sidecar-real\.spec\.ts/,
  },
  {
    name: "chat-protocol",
    testMatch: /chat-protocol\.spec\.ts/,
  },
];

// 打包态用例只在安装包已生成后加入，避免开发态 E2E 隐式依赖发布物。
if (process.env.LION_PACKAGED_APP) {
  projects.push({ name: "packaged", testMatch: /packaged\.spec\.ts/ });
}

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    trace: "off",
  },
  projects,
});
