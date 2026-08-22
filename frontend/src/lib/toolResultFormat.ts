// 工具执行结果的展示形态判定与 ANSI 解析。
// 全部为纯函数：ToolResultView 只负责渲染，判定逻辑集中在此便于单测。

export type ToolResultFormat = "diff" | "ansi" | "markdown" | "text";

// unified diff hunk 头（@@ -起始,行数 +起始,行数 @@），行数省略时默认 1；
// 后端 _generate_diff（lion_code/tools.py）产出即此格式，前面还带一段成功说明
const DIFF_HUNK_RE = /^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/m;

export function hasDiffHunk(result: string): boolean {
  return DIFF_HUNK_RE.test(result);
}

// CSI（\x1b[...，含颜色与光标控制）或 OSC（\x1b]...，窗口标题）出现即判为终端输出；
// 非 SGR 序列在 parseAnsiToSpans 渲染时剥离，避免用户看到裸转义码
export function hasAnsiEscape(text: string): boolean {
  return text.includes("\x1b[") || text.includes("\x1b]");
}

export function isAgentTool(name: string): boolean {
  // agent 是唯一暴露的子任务工具（tooling/internal.py），按 PRD 精确匹配
  return name === "agent";
}

// 以下分类的关键字与判定顺序须和 ToolView.getToolConfig 保持一致，
// 否则同一工具的头部图标与结果渲染会归入两个不同分支
export function isCommandTool(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.includes("command") ||
    lower.includes("bash") ||
    lower.includes("shell") ||
    lower.includes("exec")
  );
}

export function isWriteTool(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.includes("write") || lower.includes("create");
}

export function isEditTool(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.includes("replace") || lower.includes("edit");
}

export function pickResultFormat(
  toolName: string,
  result: string,
): ToolResultFormat {
  if (isAgentTool(toolName)) return "markdown";
  if (isCommandTool(toolName)) return hasAnsiEscape(result) ? "ansi" : "text";
  // 写入类结果是行号预览而非 diff 形态，保持纯文本
  if (isWriteTool(toolName)) return "text";
  if (isEditTool(toolName)) return hasDiffHunk(result) ? "diff" : "text";
  return "text";
}

// ─── ANSI 解析 ─────────────────────────────────────────────

export interface AnsiSpan {
  text: string;
  fg?: string;
  bg?: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
}

interface AnsiStyle {
  fg?: string;
  bg?: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
}

// Campbell 调色板（Windows Terminal 默认）。0 号前景（纯黑）在深底卡片上不可见，
// 提亮为亮黑灰，其余与标准终端一致
const FG = [
  "#767676",
  "#c50f1f",
  "#13a10e",
  "#c19c00",
  "#0037da",
  "#881798",
  "#3a96dd",
  "#cccccc",
];
const FG_BRIGHT = [
  "#767676",
  "#e74856",
  "#16c60c",
  "#f9f1a5",
  "#3b78ff",
  "#b4009e",
  "#61d6d6",
  "#f2f2f2",
];
const BG = [
  "#0c0c0c",
  "#c50f1f",
  "#13a10e",
  "#c19c00",
  "#0037da",
  "#881798",
  "#3a96dd",
  "#cccccc",
];
const BG_BRIGHT = [
  "#767676",
  "#e74856",
  "#16c60c",
  "#f9f1a5",
  "#3b78ff",
  "#b4009e",
  "#61d6d6",
  "#f2f2f2",
];

// 256 色表：16-231 是 6×6×6 立方体、232-255 是灰阶，公式为 xterm 标准
function color256(n: number): string {
  if (n < 8) return FG[n];
  if (n < 16) return FG_BRIGHT[n - 8];
  if (n < 232) {
    const levels = [0, 95, 135, 175, 215, 255];
    const i = n - 16;
    const r = levels[Math.floor(i / 36)];
    const g = levels[Math.floor((i % 36) / 6)];
    const b = levels[i % 6];
    return `rgb(${r}, ${g}, ${b})`;
  }
  const gray = 8 + (n - 232) * 10;
  return `rgb(${gray}, ${gray}, ${gray})`;
}

// 应用一段 SGR 参数。只实现会影响呈现的子集（颜色/加粗/斜体/下划线/重置），
// 其余码（闪烁、反相等）消费掉但不产生样式；38/48 扩展色参数不足时放弃整个
// 序列——渲染为无色比错色安全
function applySgr(style: AnsiStyle, params: readonly number[]): void {
  let i = 0;
  while (i < params.length) {
    const code = params[i];
    if (!Number.isFinite(code)) {
      i += 1;
      continue;
    }
    if (code === 0) {
      style.fg = undefined;
      style.bg = undefined;
      style.bold = undefined;
      style.italic = undefined;
      style.underline = undefined;
    } else if (code === 1) style.bold = true;
    else if (code === 3) style.italic = true;
    else if (code === 4) style.underline = true;
    else if (code === 22) style.bold = false;
    else if (code === 23) style.italic = false;
    else if (code === 24) style.underline = false;
    else if (code === 39) style.fg = undefined;
    else if (code === 49) style.bg = undefined;
    else if (code >= 30 && code <= 37) style.fg = FG[code - 30];
    else if (code >= 90 && code <= 97) style.fg = FG_BRIGHT[code - 90];
    else if (code >= 40 && code <= 47) style.bg = BG[code - 40];
    else if (code >= 100 && code <= 107) style.bg = BG_BRIGHT[code - 100];
    else if (code === 38 || code === 48) {
      const mode = params[i + 1];
      let color: string | null = null;
      let next = i;
      if (mode === 5 && params.length >= i + 3) {
        color = color256(params[i + 2]);
        next = i + 3;
      } else if (mode === 2 && params.length >= i + 5) {
        color = `rgb(${params[i + 2]}, ${params[i + 3]}, ${params[i + 4]})`;
        next = i + 5;
      }
      if (color === null) return;
      if (code === 38) style.fg = color;
      else style.bg = color;
      i = next;
      continue;
    }
    i += 1;
  }
}

// 覆盖 CSI（含 SGR 与光标控制）和 OSC（以 BEL 或 ST 结尾）；除 SGR 外全部剥离
const ANSI_ESCAPE_RE =
  /\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))/g;

export function parseAnsiToSpans(text: string): AnsiSpan[] {
  // 单独 \r 是进度条的覆写帧：真实终端只保留最后一帧，但 HTML 没有覆写语义，
  // 折叠为换行逐帧展示，信息更全且行为确定
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const spans: AnsiSpan[] = [];
  const style: AnsiStyle = {};
  let lastIndex = 0;

  for (const match of normalized.matchAll(ANSI_ESCAPE_RE)) {
    const seq = match[0];
    const chunk = normalized.slice(lastIndex, match.index ?? 0);
    if (chunk) spans.push({ text: chunk, ...style });
    if (seq.startsWith("\x1b[") && seq.endsWith("m")) {
      // 空参数（\x1b[m）按 reset 处理，与终端行为一致
      applySgr(
        style,
        seq
          .slice(2, -1)
          .split(";")
          .map((p) => (p === "" ? 0 : Number(p))),
      );
    }
    lastIndex = (match.index ?? 0) + seq.length;
  }
  const tail = normalized.slice(lastIndex);
  if (tail) spans.push({ text: tail, ...style });
  return spans;
}
