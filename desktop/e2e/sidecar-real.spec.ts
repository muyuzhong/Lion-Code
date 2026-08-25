import { createServer } from "node:http";
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

test("streams output from a configured local OpenAI-compatible Provider", async () => {
  const root = await mkdtemp(join(tmpdir(), "lion-electron-provider-"));
  const workspace = join(root, "workspace");
  const home = join(root, "home");
  await Promise.all([mkdir(workspace), mkdir(home)]);

  let requestCount = 0;
  let failNextRequest = false;
  const requestUrls: string[] = [];
  const provider = createServer((request, response) => {
    requestCount += 1;
    requestUrls.push(request.url ?? "");
    if (request.method !== "POST" || request.url !== "/v1/chat/completions") {
      response.writeHead(404).end();
      return;
    }
    request.resume();
    request.on("end", () => {
      if (failNextRequest) {
        failNextRequest = false;
        response.writeHead(400, { "Content-Type": "application/json" });
        response.end('{"error":{"message":"provider rejected"}}');
        return;
      }
      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });
      response.write('data: {"choices":[{"delta":{"content":"本地模型回答"},"finish_reason":null}]}\n\n');
      response.write('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n');
      response.end("data: [DONE]\n\n");
    });
  });
  await new Promise<void>((resolve, reject) => {
    provider.once("error", reject);
    provider.listen(0, "127.0.0.1", resolve);
  });
  const address = provider.address();
  if (!address || typeof address === "string") throw new Error("本地 Provider 未绑定端口");

  const application = await electron.launch({
    args: ["."],
    env: {
      ...process.env,
      PYTHONPATH: resolve(".."),
      LION_SIDECAR_STATE_HOME: home,
      NO_PROXY: "127.0.0.1,localhost",
      no_proxy: "127.0.0.1,localhost",
      HTTP_PROXY: "",
      HTTPS_PROXY: "",
      ALL_PROXY: "",
      http_proxy: "",
      https_proxy: "",
      all_proxy: "",
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

    await expect(page.getByRole("heading", { name: "Provider 与模型" })).toBeVisible();
    await expect(page.getByRole("button", { name: "保存配置" })).toBeEnabled();
    await page.locator("#provider-select").selectOption("openai");
    await page.getByRole("textbox", { name: "API key" }).fill("local-test-key");
    await page.getByRole("textbox", { name: "API 地址" }).fill(`http://127.0.0.1:${address.port}/v1`);
    await page.getByRole("button", { name: "保存配置" }).click();
    await expect(page.getByRole("heading", { name: "Provider 与模型" })).toBeHidden();
    await page.getByRole("button", { name: "打开模型设置" }).click();
    await expect(page.locator("#provider-select")).toHaveValue("openai");
    await expect(page.locator("#provider-base-url")).toHaveValue(`http://127.0.0.1:${address.port}/v1`);
    await page.getByRole("button", { name: "关闭设置" }).click();

    const composer = page.getByRole("textbox", { name: "消息" });
    await composer.fill("hi");
    await page.getByRole("button", { name: "发送" }).click();
    await expect.poll(() => requestUrls[0] ?? "", { timeout: 5_000 }).toBe("/v1/chat/completions");
    await expect(page.getByText("本地模型回答", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "发送" })).toBeVisible({ timeout: 15_000 });

    failNextRequest = true;
    await composer.fill("error");
    await page.getByRole("button", { name: "发送" }).click();
    await expect(page.getByText("生成未完成。检查连接后重试。", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "发送" })).toBeVisible({ timeout: 15_000 });

    await composer.fill("again");
    await page.getByRole("button", { name: "发送" }).click();
    await expect.poll(() => requestCount, { timeout: 5_000 }).toBe(3);
    await expect(page.getByText("本地模型回答", { exact: true })).toHaveCount(2, { timeout: 15_000 });
  } finally {
    await application.close();
    await new Promise<void>((resolve, reject) => provider.close((error) => error ? reject(error) : resolve()));
  }
});
