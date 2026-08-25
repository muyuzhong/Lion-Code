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

test("restores Provider settings and surfaces a missing API error", async () => {
  const root = await mkdtemp(join(tmpdir(), "lion-electron-config-"));
  const workspace = join(root, "workspace");
  const home = join(root, "home");
  await Promise.all([mkdir(workspace), mkdir(home)]);
  const env: Record<string, string | undefined> = {
    ...process.env,
    PYTHONPATH: resolve(".."),
    LION_SIDECAR_STATE_HOME: home,
  };
  delete env.OPENAI_API_KEY;
  delete env.OPENAI_BASE_URL;
  delete env.ANTHROPIC_API_KEY;
  delete env.ANTHROPIC_BASE_URL;
  const launchEnv = Object.fromEntries(Object.entries(env).filter(([, value]) => value !== undefined)) as Record<string, string>;
  const application = await electron.launch({ args: ["."], env: launchEnv });
  const connect = async (page: Awaited<ReturnType<typeof application.firstWindow>>) => {
    await page.evaluate(async (path) => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      await global.lionDesktop.connectWorkspace(path);
    }, workspace);
    await expect.poll(() => page.evaluate(async () => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      return (await global.lionDesktop.getBootstrapState()).phase;
    }), { timeout: 60_000 }).toBe("ready");
  };
  try {
    const page = await application.firstWindow();
    await connect(page);

    await expect(page.getByRole("heading", { name: "Provider 与模型" })).toBeVisible();
    await page.getByRole("button", { name: "保留当前配置" }).click();
    const composer = page.getByRole("textbox", { name: "消息" });
    await composer.fill("检查未配置 API");
    await page.getByRole("button", { name: "发送" }).click();
    await expect(page.getByText(/API 未配置/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "发送" })).toBeVisible();

    await page.getByRole("button", { name: "打开模型设置" }).click();
    const apiKey = page.getByRole("textbox", { name: "API key" });
    await apiKey.fill("preview-test-key");
    await page.getByRole("textbox", { name: "API 地址" }).fill("http://127.0.0.1:1/v1");
    await page.getByRole("button", { name: "保存配置" }).click();
    await expect(page.getByRole("heading", { name: "Provider 与模型" })).toBeHidden();

    await page.getByRole("button", { name: "打开模型设置" }).click();
    await expect(page.getByRole("textbox", { name: "API key" })).toHaveValue("preview-test-key");
    await expect(page.getByRole("textbox", { name: "API key" })).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: /API key/ }).click();
    await expect(page.getByRole("textbox", { name: "API key" })).toHaveAttribute("type", "text");

    await page.getByRole("button", { name: "关闭设置" }).click();
    await page.evaluate(async () => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      await global.lionDesktop.disconnect();
    });
    await expect.poll(() => page.evaluate(async () => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      return (await global.lionDesktop.getBootstrapState()).phase;
    }), { timeout: 20_000 }).toBe("exited");
    await connect(page);
    await page.getByRole("button", { name: "打开模型设置" }).click();
    await expect(page.getByRole("textbox", { name: "API key" })).toHaveValue("preview-test-key");
  } finally {
    await application.close();
  }
});
