import { describe, expect, it } from "vitest";
import { isTrustedIpcSender } from "../src/main/ipc-contract";

describe("IPC sender contract", () => {
  it("requires the exact window and lion app frame", () => {
    expect(isTrustedIpcSender("lion://app/", 7, 7)).toBe(true);
    expect(isTrustedIpcSender("lion://application/", 7, 7)).toBe(false);
    expect(isTrustedIpcSender("lion://app/", 8, 7)).toBe(false);
    expect(isTrustedIpcSender(null, 7, 7)).toBe(false);
  });
});
