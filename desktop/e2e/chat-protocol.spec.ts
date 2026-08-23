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
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("http://127.0.0.1:43123/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      const payloads: Record<string, unknown> = {
        "/api/messages": [{ id: "history-1", role: "assistant", content: "历史消息", tools: [] }],
        "/api/status": { session_id: "session-current", model: "claude-sonnet", provider_name: "anthropic", permission_mode: "default", api_configured: true, cwd: workspace, thinking_level: "medium", available_thinking_levels: ["off", "medium", "high"], input_tokens: 1200, output_tokens: 340, is_running: false },
        "/api/sessions": [{ id: "session-current", startTime: new Date().toISOString(), messageCount: 8, cwd: workspace }],
        "/api/models": [{ provider_name: "anthropic", model: "claude-sonnet" }],
        "/api/skills": [{ name: "review", description: "检查当前改动的关键风险" }],
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payloads[path] ?? { success: true }) });
    });
    await page.evaluate(() => {
      const target = globalThis as typeof globalThis & { __lionActions?: unknown[] };
      (globalThis as { localStorage: { removeItem(key: string): void } }).localStorage.removeItem("lion-theme");
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
    await expect(page.getByText("已连接", { exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "消息" }).fill("新问题");
    await page.getByRole("button", { name: "发送" }).click();
    await expect.poll(() => page.evaluate(() => (globalThis as typeof globalThis & { __lionActions?: unknown[] }).__lionActions)).toContainEqual({ action: "prompt", prompt: "新问题" });
    await page.waitForTimeout(100);
    expect(pageErrors).toEqual([]);
    await expect(page.getByRole("region", { name: "Lion 聊天" })).toHaveAttribute("data-message-count", "3");
    await expect(page.getByText("新问题")).toBeVisible();
    await expect(page.getByText("流式回答")).toHaveCount(1);
    await page.setViewportSize({ width: 1280, height: 720 });
    expect(await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("chat-mvp-1280x720.png") });
    await page.getByRole("button", { name: "深色" }).click();
    await page.setViewportSize({ width: 2560, height: 1440 });
    expect(await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("chat-mvp-dark-2560x1440.png") });
  } finally {
    await application.close();
  }
});
