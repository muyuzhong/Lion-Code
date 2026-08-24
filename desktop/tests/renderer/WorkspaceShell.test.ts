import { describe, expect, it } from "vitest";
import { formatRelativeTime } from "../../src/renderer/src/WorkspaceShell";

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
});
