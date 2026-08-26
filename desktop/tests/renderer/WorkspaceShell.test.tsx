// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { BackendBootstrap, WebSocketPort } from "../../src/renderer/src/backend";
import { LionRuntimeProvider } from "../../src/renderer/src/assistantRuntime";
import { ProviderSettings, formatRelativeTime } from "../../src/renderer/src/WorkspaceShell";

class FakeSocket implements WebSocketPort {
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  send(_data: string): void {}
  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }
}

function settingsBootstrap(options: { saveFails?: boolean } = {}): BackendBootstrap {
  return {
    endpoint: { baseUrl: "http://127.0.0.1:4567", capability: "a".repeat(32) },
    fetch: async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/config/provider") && init?.method === "POST" && options.saveFails) {
        return new Response(JSON.stringify({ detail: "配置写入失败" }), { status: 400 });
      }
      const payload = url.endsWith("/api/messages") ? []
        : url.endsWith("/api/status") ? { session_id: "s1", model: "model-a", provider_name: "anthropic", permission_mode: "default", api_configured: true, cwd: "C:/work", thinking_level: "medium", available_thinking_levels: ["off", "medium"], input_tokens: 0, output_tokens: 0, is_running: false }
          : url.endsWith("/api/sessions") ? []
            : url.endsWith("/api/models") ? [{ provider_name: "anthropic", model: "model-a" }]
              : url.endsWith("/api/skills") ? []
                : url.endsWith("/api/config/provider") ? { provider: "anthropic", model: "model-a", api_key: "test-secret", base_url: "https://api.anthropic.com/v1" }
                : url.endsWith("/api/config/egress") ? { allow_hosts: ["api.github.com", "example.com"] }
                : { success: true };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    },
    createWebSocket: () => new FakeSocket(),
    scheduleReconnect: () => 1,
    cancelReconnect: () => {},
  };
}

async function mountSettings(bootstrap: BackendBootstrap, onClose = vi.fn()): Promise<{ container: HTMLDivElement; root: Root; onClose: ReturnType<typeof vi.fn> }> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<LionRuntimeProvider bootstrap={bootstrap}><ProviderSettings onClose={onClose} /></LionRuntimeProvider>);
  });
  await vi.waitFor(() => expect((container.querySelector("#provider-api-key") as HTMLInputElement | null)?.value).toBe("test-secret"));
  return { container, root, onClose };
}

describe("desktop workspace presentation", () => {
  const now = Date.parse("2026-08-24T12:00:00Z");

  it("formats recent session timestamps without adding a date dependency", () => {
    expect(formatRelativeTime("2026-08-24T11:59:30Z", now)).toBe("刚刚");
    expect(formatRelativeTime("2026-08-24T11:45:00Z", now)).toBe("15 分钟前");
    expect(formatRelativeTime("2026-08-22T12:00:00Z", now)).toBe("2 天前");
  });

  it("fails closed for missing or malformed timestamps", () => {
    expect(formatRelativeTime(null, now)).toBe("时间未知");
    expect(formatRelativeTime("not-a-date", now)).toBe("时间未知");
  });

  it("loads canonical Provider fields, masks the key, and resets visibility on remount", async () => {
    const mounted = await mountSettings(settingsBootstrap());
    const apiKey = mounted.container.querySelector("#provider-api-key") as HTMLInputElement;
    expect(apiKey.type).toBe("password");
    expect(apiKey.value).toBe("test-secret");
    expect((mounted.container.querySelector("#provider-select") as HTMLSelectElement).value).toBe("anthropic");
    expect((mounted.container.querySelector("#model-select") as HTMLSelectElement).value).toBe("model-a");
    expect((mounted.container.querySelector("#provider-base-url") as HTMLInputElement).value).toBe("https://api.anthropic.com/v1");

    await act(async () => {
      (mounted.container.querySelector('button[aria-label="显示 API key"]') as HTMLButtonElement).click();
    });
    expect(apiKey.type).toBe("text");
    expect(mounted.container.querySelector('button[aria-label="隐藏 API key"]')).not.toBeNull();

    await act(async () => { mounted.root.unmount(); });
    mounted.container.remove();
    const reopened = await mountSettings(settingsBootstrap());
    expect((reopened.container.querySelector("#provider-api-key") as HTMLInputElement).type).toBe("password");
    await act(async () => { reopened.root.unmount(); });
    reopened.container.remove();
  });

  it("keeps settings open and shows the canonical save error", async () => {
    const onClose = vi.fn();
    const mounted = await mountSettings(settingsBootstrap({ saveFails: true }), onClose);
    await act(async () => {
      (mounted.container.querySelector("form") as HTMLFormElement).requestSubmit();
      await vi.waitFor(() => expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain("配置写入失败"));
    });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => { mounted.root.unmount(); });
    mounted.container.remove();
  });

  it("loads and saves egress allow_hosts in settings panel", async () => {
    let savedEgressPayload: unknown = null;
    const customBootstrap: BackendBootstrap = {
      ...settingsBootstrap(),
      fetch: async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/config/egress") && init?.method === "POST") {
          savedEgressPayload = JSON.parse(String(init.body));
          return new Response(JSON.stringify({ success: true, allow_hosts: ["api.github.com", "example.com", "new.host.org"] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return settingsBootstrap().fetch(input, init);
      },
    };
    const onClose = vi.fn();
    const mounted = await mountSettings(customBootstrap, onClose);
    const textarea = mounted.container.querySelector("#egress-allow-hosts") as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    await vi.waitFor(() => expect(textarea.value).toContain("api.github.com\nexample.com"));

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
      nativeSetter?.call(textarea, "api.github.com\nexample.com\nnew.host.org");
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
      (mounted.container.querySelector("form") as HTMLFormElement).requestSubmit();
    });

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(savedEgressPayload).toEqual({
      allow_hosts: ["api.github.com", "example.com", "new.host.org"],
    });
    await act(async () => { mounted.root.unmount(); });
    mounted.container.remove();
  });
});
