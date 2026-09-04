// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  adapter: {
    reloadOpenedResource: vi.fn(),
    fetchGitReview: vi.fn(),
    fetchGitReviewDiff: vi.fn(),
  },
  snapshot: { openedResource: null as unknown },
}));

vi.mock("../../src/renderer/src/assistantRuntime", () => ({
  useLionRuntime: () => runtime,
}));

import { WorkPanel } from "../../src/renderer/src/components/WorkPanel";

async function mountPanel(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<WorkPanel onClose={vi.fn()} onResizeBy={vi.fn()} onResizeStart={vi.fn()} />);
  });
  return { container, root };
}

describe("WorkPanel file resources", () => {
  beforeEach(() => {
    runtime.adapter.reloadOpenedResource.mockReset();
    runtime.snapshot.openedResource = null;
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  it("renders a loaded resource read-only and exposes reload", async () => {
    runtime.snapshot.openedResource = {
      ref: { path: "notes.md" },
      response: {
        status: "ready",
        path: "C:/work/notes.md",
        name: "notes.md",
        format: "markdown",
        size: 9,
        modifiedAtNs: "1710000000000000000",
        content: "# Notes",
        message: null,
      },
      loading: false,
      error: null,
    };
    const mounted = await mountPanel();

    expect(mounted.container.textContent).toContain("notes.md");
    expect(mounted.container.textContent).toContain("Notes");
    expect(mounted.container.querySelector("textarea, input")).toBeNull();
    const reload = mounted.container.querySelector<HTMLButtonElement>("button[aria-label='重新加载文件']");
    expect(reload).not.toBeNull();
    await act(async () => reload?.click());
    expect(runtime.adapter.reloadOpenedResource).toHaveBeenCalledTimes(1);
    await act(async () => mounted.root.unmount());
  });

  it("shows a typed resource failure without content", async () => {
    runtime.snapshot.openedResource = {
      ref: { path: "image.bin" },
      response: {
        status: "binary",
        path: "C:/work/image.bin",
        name: "image.bin",
        format: "text",
        size: 4,
        modifiedAtNs: null,
        content: null,
        message: "二进制资源不在文件视图中内联展示",
      },
      loading: false,
      error: null,
    };
    const mounted = await mountPanel();

    expect(mounted.container.textContent).toContain("二进制文件");
    expect(mounted.container.textContent).toContain("二进制资源不在文件视图中内联展示");
    expect(mounted.container.textContent).not.toContain("secret");
    await act(async () => mounted.root.unmount());
  });
});
