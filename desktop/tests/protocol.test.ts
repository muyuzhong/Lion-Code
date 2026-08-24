import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { resolveDevProxyUrl, resolveRendererPath } from "../src/main/renderer-path";

describe("lion protocol path", () => {
  const root = resolve("out/renderer");

  it("maps the application root to index.html", () => {
    expect(resolveRendererPath(root, "lion://app/")).toBe(resolve(root, "index.html"));
  });

  it.each(["lion://other/", "lion://app/%2e%2e%2fsecret", "https://app/index.html"])(
    "rejects an invalid or escaping URL",
    (url) => expect(() => resolveRendererPath(root, url)).toThrow(),
  );

  it("keeps development proxy requests on the configured origin", () => {
    expect(resolveDevProxyUrl(root, "lion://app/assets/main.js", "http://127.0.0.1:5173/")).toBe(
      "http://127.0.0.1:5173/assets/main.js",
    );
    expect(resolveDevProxyUrl(root, "lion://app//evil.example/x", "http://127.0.0.1:5173/")).toBe(
      "http://127.0.0.1:5173/evil.example/x",
    );
  });
});
