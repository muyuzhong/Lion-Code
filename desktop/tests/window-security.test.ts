import { describe, expect, it } from "vitest";
import { isTrustedRendererUrl, secureWebPreferences } from "../src/main/window-security";

describe("BrowserWindow security", () => {
  it("locks the renderer sandbox boundary", () => {
    expect(secureWebPreferences("preload.js")).toMatchObject({
      preload: "preload.js", nodeIntegration: false, contextIsolation: true, sandbox: true,
    });
  });

  it("accepts only the exact lion app host", () => {
    expect(isTrustedRendererUrl("lion://app/settings")).toBe(true);
    expect(isTrustedRendererUrl("lion://application/")).toBe(false);
    expect(isTrustedRendererUrl("https://app/")).toBe(false);
  });
});
