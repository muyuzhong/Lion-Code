import { describe, expect, it, vi } from "vitest";

import {
  capabilityHeaders,
  getCapability,
  importCapabilityFromLocation,
  websocketProtocols,
} from "./capability";

const CAPABILITY = "A".repeat(43);

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

function browserContext(hash: string, storage = new MemoryStorage()) {
  return {
    browser: {
      location: {
        hash,
        pathname: "/chat",
        search: "?view=current",
      },
      history: {
        state: { page: "chat" },
        replaceState: vi.fn(),
      },
      sessionStorage: storage,
    },
    storage,
  };
}

describe("browser capability bootstrap", () => {
  it("imports the fragment into session storage and removes it from the URL", () => {
    const { browser, storage } = browserContext(`#capability=${CAPABILITY}`);

    expect(importCapabilityFromLocation(browser)).toBe(CAPABILITY);
    expect(getCapability(storage)).toBe(CAPABILITY);
    expect(browser.history.replaceState).toHaveBeenCalledWith(
      { page: "chat" },
      "",
      "/chat?view=current",
    );
  });

  it("rejects an invalid fragment instead of retaining an old capability", () => {
    const { browser, storage } = browserContext("#capability=not-valid");
    storage.setItem("lion-code-capability", CAPABILITY);

    expect(importCapabilityFromLocation(browser)).toBeNull();
    expect(getCapability(storage)).toBeNull();
    expect(browser.history.replaceState).toHaveBeenCalledOnce();
  });

  it("reuses the current tab capability when the fragment is absent", () => {
    const { browser, storage } = browserContext("");
    storage.setItem("lion-code-capability", CAPABILITY);

    expect(importCapabilityFromLocation(browser)).toBe(CAPABILITY);
    expect(browser.history.replaceState).not.toHaveBeenCalled();
  });
});

describe("authenticated transports", () => {
  it("adds the REST Bearer header without overwriting content type", () => {
    const storage = new MemoryStorage();
    storage.setItem("lion-code-capability", CAPABILITY);

    const headers = capabilityHeaders(
      { "Content-Type": "application/json" },
      storage,
    );

    expect(headers.get("Authorization")).toBe(`Bearer ${CAPABILITY}`);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("uses a WebSocket subprotocol instead of putting capability in the URL", () => {
    expect(websocketProtocols(CAPABILITY)).toEqual([
      "lion-code",
      `lion-code-capability.${CAPABILITY}`,
    ]);
    expect(websocketProtocols("not-valid")).toEqual([]);
  });
});
