import { describe, expect, it } from "vitest";
import { parseReadyLine, sanitizeDiagnosticText, tailText } from "../src/main/ready";

const capability = "a".repeat(32);

describe("ready protocol", () => {
  it("accepts the exact v1 schema", () => {
    expect(parseReadyLine(JSON.stringify({ type: "ready", version: 1, port: 49152, capability }))).toEqual({
      ok: true, record: { type: "ready", version: 1, port: 49152, capability },
    });
  });

  it.each([
    { type: "ready", version: 1, port: 49152, capability, extra: true },
    { type: "ready", version: 2, port: 49152, capability },
    { type: "ready", version: 1, port: 0, capability },
    { type: "ready", version: 1, port: 49152, capability: "short" },
  ])("rejects invalid records", (record) => expect(parseReadyLine(JSON.stringify(record)).ok).toBe(false));

  it("redacts known capability before retaining the diagnostic tail", () => {
    expect(tailText(sanitizeDiagnosticText(`failure ${capability}`, [capability]), 30)).not.toContain(capability);
  });
});
