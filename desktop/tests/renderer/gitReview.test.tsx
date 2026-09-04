// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GitReviewDiff, GitReviewSnapshot } from "../../src/renderer/src/backend";

const runtime = vi.hoisted(() => ({
  adapter: {
    fetchGitReview: vi.fn(),
    fetchGitReviewDiff: vi.fn(),
  },
}));

vi.mock("../../src/renderer/src/assistantRuntime", () => ({
  useLionRuntime: () => ({ adapter: runtime.adapter, snapshot: { openedResource: null } }),
}));

import { WorkPanel } from "../../src/renderer/src/components/WorkPanel";

const dirtySnapshot: GitReviewSnapshot = {
  state: "ok",
  branch: "main",
  revision: "revision-1",
  clean: false,
  truncated: false,
  files: [
    {
      path: "a.py",
      status: "modified",
      additions: 1,
      deletions: 0,
      binary: false,
    },
  ],
  additions_total: 1,
  deletions_total: 0,
};

const textDiff: GitReviewDiff = {
  path: "a.py",
  diff: "@@ -1 +1 @@\n-x = 1\n+x = 2\n",
  binary: false,
  truncated: false,
  untracked: false,
};

function buttonWithText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(text),
  );
  if (!(button instanceof HTMLButtonElement)) throw new Error(`button not found: ${text}`);
  return button;
}

async function mountPanel(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <WorkPanel
        onClose={vi.fn()}
        onResizeBy={vi.fn()}
        onResizeStart={vi.fn()}
      />,
    );
  });
  await act(async () => {
    buttonWithText(container, "Git").click();
  });
  await vi.waitFor(() => expect(runtime.adapter.fetchGitReview).toHaveBeenCalledTimes(1));
  await vi.waitFor(() => expect(container.textContent).toContain("a.py"));
  return { container, root };
}

describe("WorkPanel Git review", () => {
  beforeEach(() => {
    runtime.adapter.fetchGitReview.mockReset().mockResolvedValue(dirtySnapshot);
    runtime.adapter.fetchGitReviewDiff.mockReset().mockResolvedValue(textDiff);
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  it("shows a diff error when the adapter cannot read a file", async () => {
    runtime.adapter.fetchGitReviewDiff.mockResolvedValue(null);
    const mounted = await mountPanel();

    await act(async () => {
      buttonWithText(mounted.container, "a.py").click();
    });

    await vi.waitFor(() => expect(mounted.container.textContent).toContain("Git diff 读取失败"));
    expect(mounted.container.textContent).not.toContain("正在加载 diff");
    await act(async () => mounted.root.unmount());
  });

  it("distinguishes a loaded empty diff from a pending diff", async () => {
    runtime.adapter.fetchGitReviewDiff.mockResolvedValue({
      ...textDiff,
      diff: "",
    });
    const mounted = await mountPanel();

    await act(async () => {
      buttonWithText(mounted.container, "a.py").click();
    });

    await vi.waitFor(() => expect(mounted.container.textContent).toContain("没有可显示的文本 diff"));
    expect(mounted.container.textContent).not.toContain("正在加载 diff");
    await act(async () => mounted.root.unmount());
  });

  it("does not cache a diff response from before a snapshot refresh", async () => {
    let resolveOld!: (value: GitReviewDiff) => void;
    const oldDiff = new Promise<GitReviewDiff>((resolve) => {
      resolveOld = resolve;
    });
    runtime.adapter.fetchGitReviewDiff
      .mockImplementationOnce(() => oldDiff)
      .mockResolvedValueOnce(textDiff);
    const mounted = await mountPanel();

    await act(async () => {
      buttonWithText(mounted.container, "a.py").click();
      mounted.container.querySelector<HTMLButtonElement>("button[aria-label='刷新 Git 状态']")?.click();
    });
    await vi.waitFor(() => expect(runtime.adapter.fetchGitReview).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolveOld({ ...textDiff, diff: "old" });
      await Promise.resolve();
    });
    await act(async () => {
      buttonWithText(mounted.container, "a.py").click();
    });

    expect(runtime.adapter.fetchGitReviewDiff).toHaveBeenCalledTimes(2);
    await act(async () => mounted.root.unmount());
  });
});
