import { describe, expect, it } from "vitest";

import {
  hasAnsiEscape,
  hasDiffHunk,
  isAgentTool,
  isCommandTool,
  isEditTool,
  isWriteTool,
  parseAnsiToSpans,
  pickResultFormat,
} from "./toolResultFormat";

const EDIT_RESULT = [
  "Successfully edited src/app.py",
  "",
  "@@ -10,3 +10,4 @@",
  "- old line",
  "+ new line",
  "  context",
].join("\n");

describe("hasDiffHunk", () => {
  it("识别后端 _edit_file 输出中的 hunk 头", () => {
    expect(hasDiffHunk(EDIT_RESULT)).toBe(true);
  });

  it("支持省略行数的 hunk 头", () => {
    expect(hasDiffHunk("@@ -1 +1 @@")).toBe(true);
    expect(hasDiffHunk("prefix\n@@ -3,2 +3 @@\n- a")).toBe(true);
  });

  it("写入类行号预览与普通文本不误判", () => {
    expect(hasDiffHunk("Successfully wrote to x (3 lines)\n\n   1 | foo")).toBe(
      false,
    );
    expect(hasDiffHunk("@@ -a,b +c,d @@")).toBe(false);
    expect(hasDiffHunk("no diff here")).toBe(false);
  });
});

describe("hasAnsiEscape", () => {
  it("识别 SGR 颜色序列", () => {
    expect(hasAnsiEscape("\u001b[31mRED\u001b[0m")).toBe(true);
  });

  it("识别非 SGR 的 CSI 与 OSC 序列", () => {
    expect(hasAnsiEscape("clear line \u001b[2K")).toBe(true);
    expect(hasAnsiEscape("\u001b]0;title\u0007ok")).toBe(true);
  });

  it("纯文本不误判", () => {
    expect(hasAnsiEscape("plain output")).toBe(false);
    expect(hasAnsiEscape("")).toBe(false);
  });
});

describe("工具类型判定边界", () => {
  it("命令类：command/bash/shell/exec 关键字，大小写不敏感", () => {
    expect(isCommandTool("run_shell")).toBe(true);
    expect(isCommandTool("Bash")).toBe(true);
    expect(isCommandTool("execute_command")).toBe(true);
    expect(isCommandTool("edit_file")).toBe(false);
  });

  it("编辑类：edit/replace 关键字", () => {
    expect(isEditTool("edit_file")).toBe(true);
    expect(isEditTool("replace_in_file")).toBe(true);
    expect(isEditTool("write_file")).toBe(false);
  });

  it("写入类：write/create 关键字", () => {
    expect(isWriteTool("write_file")).toBe(true);
    expect(isWriteTool("create_file")).toBe(true);
    expect(isWriteTool("edit_file")).toBe(false);
  });

  it("agent 精确匹配，不吞同前缀工具", () => {
    expect(isAgentTool("agent")).toBe(true);
    expect(isAgentTool("Agent")).toBe(false);
    expect(isAgentTool("agent_tool")).toBe(false);
  });
});

describe("pickResultFormat", () => {
  it("edit 类含 hunk → diff，无 hunk（如报错文本）→ 纯文本", () => {
    expect(pickResultFormat("edit_file", EDIT_RESULT)).toBe("diff");
    expect(
      pickResultFormat("edit_file", "Error: old_string not found in x"),
    ).toBe("text");
  });

  it("write 类即使内容形似 diff 也保持纯文本预览", () => {
    expect(pickResultFormat("write_file", EDIT_RESULT)).toBe("text");
  });

  it("命令类含 ANSI → 终端卡片，无 ANSI → 纯文本", () => {
    expect(pickResultFormat("run_shell", "\u001b[32mPASS\u001b[0m")).toBe(
      "ansi",
    );
    expect(pickResultFormat("run_shell", "PASS 3 tests")).toBe("text");
  });

  it("agent 固定 Markdown，优先级最高", () => {
    expect(pickResultFormat("agent", "# 报告")).toBe("markdown");
    expect(pickResultFormat("agent", "\u001b[31mred\u001b[0m")).toBe(
      "markdown",
    );
  });

  it("未知/检索类工具一律纯文本，即使内容含 ANSI 或 hunk", () => {
    expect(pickResultFormat("web_fetch", "<html>")).toBe("text");
    expect(pickResultFormat("grep_search", "\u001b[31mmatch\u001b[0m")).toBe(
      "text",
    );
    expect(pickResultFormat("read_file", EDIT_RESULT)).toBe("text");
  });

  it("分类顺序与 getToolConfig 一致：终端 → 写入 → 编辑", () => {
    // 名称同时命中多个分支时，先命中的分支获胜（如 bash_edit 走命令分支）
    expect(pickResultFormat("bash_edit", EDIT_RESULT)).toBe("text");
    expect(pickResultFormat("edit_write_file", EDIT_RESULT)).toBe("text");
  });
});

describe("parseAnsiToSpans", () => {
  it("SGR 颜色映射为 span 前景色，reset 后回到默认", () => {
    expect(parseAnsiToSpans("\u001b[31merror\u001b[0m plain")).toEqual([
      { text: "error", fg: "#c50f1f" },
      { text: " plain" },
    ]);
  });

  it("组合参数（1;32）与空 reset（\\x1b[m）", () => {
    expect(parseAnsiToSpans("\u001b[1;32mOK\u001b[m")).toEqual([
      { text: "OK", fg: "#13a10e", bold: true },
    ]);
  });

  it("39/49 恢复默认前景/背景", () => {
    expect(parseAnsiToSpans("\u001b[31mA\u001b[39mB")).toEqual([
      { text: "A", fg: "#c50f1f" },
      { text: "B" },
    ]);
  });

  it("38;2 真彩与 38;5 256 色", () => {
    expect(parseAnsiToSpans("\u001b[38;2;255;0;0mR")).toEqual([
      { text: "R", fg: "rgb(255, 0, 0)" },
    ]);
    expect(parseAnsiToSpans("\u001b[38;5;196mX")).toEqual([
      { text: "X", fg: "rgb(255, 0, 0)" },
    ]);
  });

  it("38 扩展色参数不足时放弃整个序列，不产生错误样式", () => {
    expect(parseAnsiToSpans("\u001b[38;5mX")).toEqual([{ text: "X" }]);
  });

  it("非 SGR 序列（光标控制、OSC 标题）直接剥离", () => {
    // 序列两侧文本成为两个相邻的默认样式 span，呈现上等价于拼接
    expect(parseAnsiToSpans("a\u001b[2Kb")).toEqual([{ text: "a" }, { text: "b" }]);
    expect(parseAnsiToSpans("\u001b]0;title\u0007x")).toEqual([{ text: "x" }]);
  });

  it("0 号前景按偏离决策提亮为 #767676（纯黑在深底卡片不可见）", () => {
    expect(parseAnsiToSpans("\u001b[30mok")).toEqual([
      { text: "ok", fg: "#767676" },
    ]);
  });

  it("背景色与亮色系", () => {
    expect(parseAnsiToSpans("\u001b[42;93mwarn")).toEqual([
      { text: "warn", fg: "#f9f1a5", bg: "#13a10e" },
    ]);
  });

  it("单独 \\r 折叠为换行（进度条帧展开）", () => {
    expect(parseAnsiToSpans("loading...\rdone")).toEqual([
      { text: "loading...\ndone" },
    ]);
    expect(parseAnsiToSpans("a\r\nb")).toEqual([{ text: "a\nb" }]);
  });

  it("纯文本与空串", () => {
    expect(parseAnsiToSpans("hello")).toEqual([{ text: "hello" }]);
    expect(parseAnsiToSpans("")).toEqual([]);
  });
});
