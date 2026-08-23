import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { DesktopBridge } from "../src/shared/types";

test("bootstraps REST history and streams one assistant-ui message over mocked WS", async () => {
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
    await page.route("http://127.0.0.1:43123/api/messages", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: "history-1", role: "assistant", content: "历史消息", tools: [] }]),
    }));
    await page.evaluate(() => {
      const target = globalThis as typeof globalThis & { __lionActions?: unknown[] };
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
  } finally {
    await application.close();
  }
});
