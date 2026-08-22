const CAPABILITY_FRAGMENT_KEY = "capability";
const CAPABILITY_STORAGE_KEY = "lion-code-capability";
const CAPABILITY_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

export const WEBSOCKET_PROTOCOL = "lion-code";
const WEBSOCKET_CAPABILITY_PREFIX = "lion-code-capability.";

type CapabilityBrowser = {
  location: Pick<Location, "hash" | "pathname" | "search">;
  history: Pick<History, "replaceState" | "state">;
  sessionStorage: Pick<Storage, "getItem" | "setItem" | "removeItem">;
};

function isCapability(value: string | null): value is string {
  return value !== null && CAPABILITY_PATTERN.test(value);
}

export function getCapability(
  storage: Pick<Storage, "getItem" | "removeItem"> = window.sessionStorage,
): string | null {
  const capability = storage.getItem(CAPABILITY_STORAGE_KEY);
  if (isCapability(capability)) return capability;

  if (capability !== null) storage.removeItem(CAPABILITY_STORAGE_KEY);
  return null;
}

export function importCapabilityFromLocation(
  browser: CapabilityBrowser = window,
): string | null {
  const fragment = new URLSearchParams(browser.location.hash.slice(1));
  if (!fragment.has(CAPABILITY_FRAGMENT_KEY)) {
    return getCapability(browser.sessionStorage);
  }

  const capability = fragment.get(CAPABILITY_FRAGMENT_KEY);
  browser.history.replaceState(
    browser.history.state,
    "",
    `${browser.location.pathname}${browser.location.search}`,
  );

  if (!isCapability(capability)) {
    browser.sessionStorage.removeItem(CAPABILITY_STORAGE_KEY);
    return null;
  }

  browser.sessionStorage.setItem(CAPABILITY_STORAGE_KEY, capability);
  return capability;
}

export function capabilityHeaders(
  headers?: HeadersInit,
  storage: Pick<Storage, "getItem" | "removeItem"> = window.sessionStorage,
): Headers {
  const result = new Headers(headers);
  const capability = getCapability(storage);
  if (capability) result.set("Authorization", `Bearer ${capability}`);
  return result;
}

export function websocketProtocols(capability: string): string[] {
  if (!isCapability(capability)) return [];
  return [
    WEBSOCKET_PROTOCOL,
    `${WEBSOCKET_CAPABILITY_PREFIX}${capability}`,
  ];
}
