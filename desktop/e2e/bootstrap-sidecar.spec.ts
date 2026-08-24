import { mkdtemp, mkdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { DesktopBridge } from "../src/shared/types";

test("switches workspaces and reaps every fake sidecar", async () => {
  const root = await mkdtemp(join(tmpdir(), "lion-electron-e2e-"));
  const first = join(root, "first");
  const second = join(root, "second");
  const logPath = join(root, "sidecar.log");
  await Promise.all([mkdir(first), mkdir(second)]);
  const fixturePath = resolve("e2e/fixtures");
  const application = await electron.launch({
    args: ["."],
    env: {
      ...process.env,
      PYTHONPATH: fixturePath,
      LION_FAKE_SIDECAR_LOG: logPath,
    },
  });
  const page = await application.firstWindow();
  const connect = (workspacePath: string) => page.evaluate(async (path) => {
    const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
    await global.lionDesktop.connectWorkspace(path);
  }, workspacePath);
  const phase = () => page.evaluate(async () => {
    const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
    return (await global.lionDesktop.getBootstrapState()).phase;
  });

  await connect(first);
  await expect.poll(phase).toBe("ready");
  await connect(second);
  await expect.poll(phase).toBe("ready");
  expect(await page.evaluate(() => {
    const global = globalThis as typeof globalThis & {
      location: { href: string };
      sessionStorage: { length: number };
    };
    return { url: global.location.href, storage: global.sessionStorage.length };
  })).toEqual({ url: "lion://app/", storage: 0 });

  await application.close();
  await expect.poll(async () => (await readFile(logPath, "utf-8")).trim().split("\n")).toHaveLength(4);
  const events = (await readFile(logPath, "utf-8")).trim().split("\n").map((line) => line.split(":")[0]);
  expect(events).toEqual(["start", "stop", "start", "stop"]);
});
