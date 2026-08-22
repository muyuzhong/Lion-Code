// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchSkills } from "./api";

const CAPABILITY = "A".repeat(43);

beforeEach(() => {
  sessionStorage.setItem("lion-code-capability", CAPABILITY);
});

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("fetchSkills", () => {
  it("请求 /api/skills 并携带 capability Bearer 头，解析 SkillItem 列表", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          { name: "doc-writer", description: "撰写文档" },
          { name: "no-desc", description: null },
        ]),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const skills = await fetchSkills();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/skills");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      `Bearer ${CAPABILITY}`,
    );
    expect(skills).toEqual([
      { name: "doc-writer", description: "撰写文档" },
      { name: "no-desc", description: null },
    ]);
  });

  it("非 2xx 响应抛错（调用方 catch 后降级为空列表）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Unauthorized", { status: 401 })),
    );

    await expect(fetchSkills()).rejects.toThrow("Failed to fetch skills");
  });
});
