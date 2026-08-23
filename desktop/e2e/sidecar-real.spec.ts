import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { DesktopBridge } from "../src/shared/types";

test("connects to the real Python sidecar", async () => {
  const root = await mkdtemp(join(tmpdir(), "lion-electron-real-"));
  const workspace = join(root, "workspace");
  const home = join(root, "home");
  await Promise.all([mkdir(workspace), mkdir(home)]);
  const application = await electron.launch({
    args: ["."],
    env: {
      ...process.env,
      PYTHONPATH: resolve(".."),
      LION_SIDECAR_STATE_HOME: home,
      OPENAI_API_KEY: "e2e-placeholder",
      OPENAI_BASE_URL: "http://127.0.0.1:1",
    },
  });
  try {
    const page = await application.firstWindow();
    await page.evaluate(async (path) => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      await global.lionDesktop.connectWorkspace(path);
    }, workspace);
    await expect.poll(() => page.evaluate(async () => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      return (await global.lionDesktop.getBootstrapState()).phase;
    }), { timeout: 60_000 }).toBe("ready");
  } finally {
    await application.close();
  }
});
