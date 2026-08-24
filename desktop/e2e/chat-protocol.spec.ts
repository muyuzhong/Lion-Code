import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { DesktopBridge } from "../src/shared/types";

test("bootstraps REST history and streams one assistant-ui message over mocked WS", async ({}, testInfo) => {
  const root = await mkdtemp(join(tmpdir(), "lion-chat-e2e-"));
  const workspace = join(root, "workspace");
  await mkdir(workspace);
  const application = await electron.launch({
    args: ["."],
    env: { ...process.env, PYTHONPATH: resolve("e2e/fixtures") },
  });
  try {
    const page = await application.firstWindow();
    let sessionLabel: string | null = null;
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("http://127.0.0.1:43123/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/sessions/rename" && route.request().method() === "POST") {
        sessionLabel = (route.request().postDataJSON() as { label: string }).label;
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true }) });
      }
      const payloads: Record<string, unknown> = {
        "/api/messages": [{ id: "history-1", role: "assistant", content: "历史消息", reasoning: "先检查工作区状态。", tools: [{ id: "tool-1", toolName: "bash", args: { command: "git status --short" }, result: " M desktop/src/renderer/src/styles.css", status: "completed" }] }],
        "/api/status": { session_id: "session-current", model: "claude-sonnet", provider_name: "anthropic", permission_mode: "default", api_configured: true, cwd: workspace, thinking_level: "medium", available_thinking_levels: ["off", "medium", "high"], input_tokens: 1200, output_tokens: 340, is_running: false },
        "/api/sessions": [{ id: "session-current", label: sessionLabel, startTime: new Date().toISOString(), messageCount: 8, cwd: workspace }],
        "/api/models": [{ provider_name: "anthropic", model: "claude-sonnet" }],
        "/api/skills": [{ name: "review", description: "检查当前改动的关键风险" }],
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payloads[path] ?? { success: true }) });
    });
    await page.evaluate(() => {
      const target = globalThis as typeof globalThis & { __lionActions?: unknown[] };
      (globalThis as { localStorage: { removeItem(key: string): void } }).localStorage.removeItem("lion-theme");
      (globalThis as { localStorage: { removeItem(key: string): void } }).localStorage.removeItem("lion-sidebar-width");
      (globalThis as { localStorage: { removeItem(key: string): void } }).localStorage.removeItem("lion-work-panel-width");
      target.__lionActions = [];
      class FakeWebSocket {
        static readonly CONNECTING = 0;
        static readonly OPEN = 1;
        readyState = FakeWebSocket.CONNECTING;
        onopen: (() => void) | null = null;
        onclose: (() => void) | null = null;
        onerror: (() => void) | null = null;
        onmessage: ((event: { data: string }) => void) | null = null;
        constructor() { queueMicrotask(() => { this.readyState = FakeWebSocket.OPEN; this.onopen?.(); }); }
        send(message: string) {
          const action = JSON.parse(message);
          target.__lionActions?.push(action);
          if (action.action !== "prompt") return;
          const emptyAssistant = { role: "assistant", content: [], stopReason: "stop", errorMessage: null };
          setTimeout(() => {
            for (const event of [
              { type: "message_start", message: emptyAssistant },
              { type: "message_update", message: emptyAssistant, assistantMessageEvent: { type: "text_delta", contentIndex: 0, delta: "流式回答", partial: emptyAssistant } },
              { type: "message_end", message: { ...emptyAssistant, content: [{ type: "text", text: "流式回答" }] } },
              { type: "agent_settled" },
            ]) this.onmessage?.({ data: JSON.stringify(event) });
          }, 20);
        }
        close() { this.readyState = 3; this.onclose?.(); }
      }
      (globalThis as { WebSocket: unknown }).WebSocket = FakeWebSocket;
    });
    await page.evaluate(async (path) => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      await global.lionDesktop.connectWorkspace(path);
    }, workspace);
    await expect(page.getByText("历史消息")).toBeVisible();
    await expect(page.getByText("思考", { exact: true })).toBeVisible();
    await expect(page.getByText("bash", { exact: true })).toBeVisible();
    await expect(page.getByLabel("已连接", { exact: true })).toBeVisible();
    const composerInput = page.getByRole("textbox", { name: "消息" });
    const composerShell = page.locator(".composer-shell");
    const idleComposerShadow = await composerShell.evaluate((element) => element.ownerDocument.defaultView?.getComputedStyle(element).boxShadow);
    await composerInput.click();
    expect(await composerInput.evaluate((element) => element.ownerDocument.defaultView?.getComputedStyle(element).outlineStyle)).toBe("none");
    expect(await composerShell.evaluate((element) => element.ownerDocument.defaultView?.getComputedStyle(element).boxShadow)).toBe(idleComposerShadow);
    await composerInput.fill("/");
    await expect(page.getByRole("listbox", { name: "技能列表" })).toBeVisible();
    await expect(page.getByRole("option", { name: /\/review/ })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("skills-popover.png") });
    await page.getByRole("option", { name: /\/review/ }).click();
    await expect(composerInput).toHaveValue("/review ");
    await composerInput.fill("");
    await expect(page.locator(".composer-skill-heading")).toHaveCount(0);
    const renameButton = page.getByRole("button", { name: "重命名 session-current" }).first();
    await renameButton.click();
    const renameInput = page.getByRole("textbox", { name: "重命名 session-current" });
    await renameInput.fill("需求文档");
    await renameInput.press("Enter");
    await expect(page.getByText("需求文档", { exact: true }).first()).toBeVisible();
    await page.getByRole("toolbar", { name: "会话工具栏" }).getByRole("button", { name: "搜索会话" }).click();
    await expect(page.getByRole("textbox", { name: "搜索会话" })).toBeFocused();
    await page.getByRole("textbox", { name: "搜索会话" }).fill("missing-session");
    await expect(page.getByText("没有匹配的会话。", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "关闭搜索" }).click();
    const projectToggle = page.getByRole("button", { name: "workspace" });
    await projectToggle.click();
    await expect(projectToggle).toHaveAttribute("aria-expanded", "false");
    await projectToggle.click();
    await page.getByLabel("通知", { exact: true }).click();
    await expect(page.getByText("暂无通知", { exact: true })).toBeVisible();
    await page.getByLabel("通知", { exact: true }).click();
    await page.locator(".work-panel-switcher").click();
    await page.locator(".work-panel-context-menu").getByRole("button", { name: "浏览器" }).click();
    await expect(page.getByRole("heading", { name: "还没有打开的浏览器" })).toBeVisible();
    await page.locator(".work-panel-switcher").click();
    await page.locator(".work-panel-context-menu").getByRole("button", { name: "工作面板" }).click();
    await page.getByRole("button", { name: "打开模型设置" }).click();
    await expect(page.getByRole("heading", { name: "Provider 与模型" })).toBeVisible();
    await page.getByRole("button", { name: "关闭设置" }).click();
    await composerInput.fill("新问题");
    await page.getByRole("button", { name: "发送" }).click();
    await expect.poll(() => page.evaluate(() => (globalThis as typeof globalThis & { __lionActions?: unknown[] }).__lionActions)).toContainEqual({ action: "prompt", prompt: "新问题" });
    await page.waitForTimeout(100);
    expect(pageErrors).toEqual([]);
    await expect(page.getByRole("region", { name: "Lion 聊天" })).toHaveAttribute("data-message-count", "3");
    await expect(page.getByText("新问题")).toBeVisible();
    await expect(page.getByText("流式回答")).toHaveCount(1);
    await page.setViewportSize({ width: 1280, height: 720 });
    expect(await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")).toBe(true);
    const composer = await page.locator(".composer-shell").boundingBox();
    expect(composer).not.toBeNull();
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(720);
    expect(composer!.y + composer!.height).toBeGreaterThan(600);
    await page.screenshot({ path: testInfo.outputPath("pi-desktop-chat-1280x720.png") });
    await page.setViewportSize({ width: 1635, height: 1050 });
    const sidebarSeparator = page.getByRole("separator", { name: "调整侧栏宽度" });
    await sidebarSeparator.hover();
    await page.mouse.down();
    await page.mouse.move(360, 420);
    await page.mouse.up();
    const sidebar = await page.locator(".sidebar").boundingBox();
    expect(sidebar?.width).toBeCloseTo(360, 0);
    await page.screenshot({ path: testInfo.outputPath("pi-desktop-reference-1635x1050.png") });
    await page.getByRole("button", { name: "切换到浅色主题" }).click();
    await page.setViewportSize({ width: 2560, height: 1440 });
    expect(await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("pi-desktop-chat-light-2560x1440.png") });
  } finally {
    await application.close();
  }
});
