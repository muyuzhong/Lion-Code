import { describe, expect, it } from "vitest";
import { parseAnsiToSpans, pickResultFormat } from "../../src/renderer/src/toolPresentation";

describe("desktop tool result presentation", () => {
  it("preserves edit diff, terminal ANSI and exact agent classification", () => {
    expect(pickResultFormat("edit_file", "done\n@@ -1 +1 @@\n-old\n+new")).toBe("diff");
    expect(pickResultFormat("write_file", "@@ -1 +1 @@")).toBe("text");
    expect(pickResultFormat("run_shell", "\u001b[32mPASS\u001b[0m")).toBe("ansi");
    expect(pickResultFormat("agent", "# report")).toBe("markdown");
    expect(pickResultFormat("agent_tool", "# report")).toBe("text");
  });

  it("parses SGR styles, strips control sequences and expands carriage returns", () => {
    expect(parseAnsiToSpans("\u001b[1;32mOK\u001b[0m plain")).toEqual([
      { text: "OK", fg: "#13a10e", bold: true },
      { text: " plain" },
    ]);
    expect(parseAnsiToSpans("a\u001b[2Kb\rnext")).toEqual([
      { text: "a" },
      { text: "b\nnext" },
    ]);
  });
});
