// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "@/components/chat/ChatInput";
import { fetchMessages } from "@/lib/api";
import type { ChatMessage } from "@/types/chat";
import { useLionChat } from "./useLionChat";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/capability", () => ({
  getCapability: () => "A".repeat(43),
  websocketProtocols: (capability: string) => [
    "lion-code",
    `lion-code-capability.${capability}`,
  ],
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), info: vi.fn() },
}));

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static readonly instances: FakeWebSocket[] = [];

  readonly sent: string[] = [];
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  receive(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

beforeEach(() => {
  FakeWebSocket.instances.length = 0;
  vi.stubGlobal("WebSocket", FakeWebSocket);
  window.sessionStorage.clear();
  vi.mocked(fetchMessages).mockReset().mockResolvedValue([]);
});

afterEach(cleanup);

describe("useLionChat typed client actions", () => {
  it("sends command, continue, compact, steer, and follow-up variants", async () => {
    const { result, unmount } = renderHook(() => useLionChat("session-1"));
    const websocket = FakeWebSocket.instances[0];
    await act(async () => websocket.open());

    act(() => {
      result.current.sendMessage("/plan");
      result.current.sendMessage("/continue");
      result.current.sendMessage("/compact");
      result.current.sendSteer("change direction");
      result.current.sendFollowUp("then verify");
    });

    expect(websocket.sent.map((item) => JSON.parse(item))).toEqual([
      { action: "command", command: "/plan" },
      { action: "continue" },
      { action: "compact" },
      { action: "steer", prompt: "change direction" },
      { action: "follow_up", prompt: "then verify" },
    ]);
    unmount();
  });

  it("consumes camelCase approval requests and responds with camelCase fields", async () => {
    const { result, unmount } = renderHook(() => useLionChat("session-1"));
    const websocket = FakeWebSocket.instances[0];
    await act(async () => websocket.open());
    act(() => {
      websocket.receive({
        type: "confirm_request",
        requestId: "request-1",
        message: "Approve?",
      });
    });

    expect(result.current.confirmRequest?.requestId).toBe("request-1");
    act(() => result.current.respondConfirm("request-1", false));
    expect(JSON.parse(websocket.sent[0])).toEqual({
      action: "confirm_response",
      requestId: "request-1",
      approved: false,
    });
    unmount();
  });

  it("reconnects by replacing provisional messages with canonical history", async () => {
    vi.useFakeTimers();
    const { result, unmount } = renderHook(() => useLionChat("session-1"));
    const first = FakeWebSocket.instances[0];
    await act(async () => first.open());
    act(() => result.current.sendMessage("provisional"));
    expect(result.current.messages[0].content).toBe("provisional");

    vi.mocked(fetchMessages).mockResolvedValueOnce([
      {
        id: "msg-1",
        role: "assistant",
        content: "canonical",
        createdAt: null,
      },
    ]);
    act(() => first.onclose?.());
    act(() => vi.advanceTimersByTime(2000));
    const second = FakeWebSocket.instances[1];
    await act(async () => second.open());

    expect(result.current.messages).toEqual([
      expect.objectContaining({ id: "msg-1", content: "canonical" }),
    ]);
    unmount();
    vi.useRealTimers();
  });

  it("ignores a stale history request after a newer canonical response", async () => {
    const stale = deferred<ChatMessage[]>();
    const current = deferred<ChatMessage[]>();
    vi.mocked(fetchMessages)
      .mockImplementationOnce(() => stale.promise)
      .mockImplementationOnce(() => current.promise);

    const { result, unmount } = renderHook(() => useLionChat("session-1"));
    const websocket = FakeWebSocket.instances[0];
    act(() => websocket.open());

    await act(async () => {
      current.resolve([
        {
          id: "current",
          role: "assistant",
          content: "current history",
        },
      ]);
      await current.promise;
    });
    await act(async () => {
      stale.resolve([
        { id: "stale", role: "assistant", content: "stale history" },
      ]);
      await stale.promise;
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({ id: "current" }),
    ]);
    unmount();
  });

  it("turns malformed server payloads into a visible terminal protocol error", async () => {
    const { result, unmount } = renderHook(() => useLionChat("session-1"));
    const websocket = FakeWebSocket.instances[0];
    await act(async () => websocket.open());
    act(() => result.current.sendMessage("pending"));

    act(() => websocket.receive({ type: "server_error" }));

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.at(-1)?.error).toBe(
      "服务端消息不符合 WebSocket event 契约",
    );
    unmount();
  });
});

describe("ChatInput command control", () => {
  it("sends Plan directly through the command contract", () => {
    const onSendMessage = vi.fn();
    render(
      <ChatInput
        onSendMessage={onSendMessage}
        onCancel={vi.fn()}
        isStreaming={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Plan 模式/ }));

    expect(onSendMessage).toHaveBeenCalledWith("/plan");
  });

  it("does not send the Plan command while a run is streaming", () => {
    const onSendMessage = vi.fn();
    render(
      <ChatInput
        onSendMessage={onSendMessage}
        onCancel={vi.fn()}
        isStreaming
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Plan 模式/ }));

    expect(onSendMessage).not.toHaveBeenCalled();
  });
});
