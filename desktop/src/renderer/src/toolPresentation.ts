export type ToolResultFormat = "diff" | "ansi" | "markdown" | "text";
export interface AnsiSpan { text: string; fg?: string; bg?: string; bold?: boolean; italic?: boolean; underline?: boolean }

const DIFF_HUNK_RE = /^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/m;
const ANSI_ESCAPE_RE = /\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))/g;
const FG = ["#767676", "#c50f1f", "#13a10e", "#c19c00", "#0037da", "#881798", "#3a96dd", "#cccccc"];
const FG_BRIGHT = ["#767676", "#e74856", "#16c60c", "#f9f1a5", "#3b78ff", "#b4009e", "#61d6d6", "#f2f2f2"];
const BG = ["#0c0c0c", "#c50f1f", "#13a10e", "#c19c00", "#0037da", "#881798", "#3a96dd", "#cccccc"];
const BG_BRIGHT = ["#767676", "#e74856", "#16c60c", "#f9f1a5", "#3b78ff", "#b4009e", "#61d6d6", "#f2f2f2"];

interface AnsiStyle { fg?: string; bg?: string; bold?: boolean; italic?: boolean; underline?: boolean }

export function pickResultFormat(toolName: string, result: string): ToolResultFormat {
  if (toolName === "agent") return "markdown";
  const name = toolName.toLowerCase();
  if (["command", "bash", "shell", "exec"].some((part) => name.includes(part))) return hasAnsiEscape(result) ? "ansi" : "text";
  if (["write", "create"].some((part) => name.includes(part))) return "text";
  if (["replace", "edit"].some((part) => name.includes(part))) return DIFF_HUNK_RE.test(result) ? "diff" : "text";
  return "text";
}

export function hasAnsiEscape(text: string): boolean {
  return text.includes("\x1b[") || text.includes("\x1b]");
}

export function parseAnsiToSpans(text: string): AnsiSpan[] {
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const spans: AnsiSpan[] = [];
  const style: AnsiStyle = {};
  let lastIndex = 0;
  for (const match of normalized.matchAll(ANSI_ESCAPE_RE)) {
    const sequence = match[0];
    const chunk = normalized.slice(lastIndex, match.index ?? 0);
    if (chunk) spans.push({ text: chunk, ...style });
    if (sequence.startsWith("\x1b[") && sequence.endsWith("m")) {
      applySgr(style, sequence.slice(2, -1).split(";").map((part) => part === "" ? 0 : Number(part)));
    }
    lastIndex = (match.index ?? 0) + sequence.length;
  }
  const tail = normalized.slice(lastIndex);
  if (tail) spans.push({ text: tail, ...style });
  return spans;
}

function applySgr(style: AnsiStyle, params: readonly number[]): void {
  let index = 0;
  while (index < params.length) {
    const code = params[index];
    if (code === 0) Object.keys(style).forEach((key) => delete style[key as keyof AnsiStyle]);
    else if (code === 1) style.bold = true;
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
      const mode = params[index + 1];
      let color: string | null = null;
      let next = index;
      if (mode === 5 && params.length >= index + 3) { color = color256(params[index + 2]); next = index + 3; }
      else if (mode === 2 && params.length >= index + 5) { color = `rgb(${params[index + 2]}, ${params[index + 3]}, ${params[index + 4]})`; next = index + 5; }
      if (color === null) return;
      if (code === 38) style.fg = color; else style.bg = color;
      index = next;
      continue;
    }
    index += 1;
  }
}

function color256(value: number): string {
  if (value < 8) return FG[value];
  if (value < 16) return FG_BRIGHT[value - 8];
  if (value < 232) {
    const levels = [0, 95, 135, 175, 215, 255];
    const offset = value - 16;
    return `rgb(${levels[Math.floor(offset / 36)]}, ${levels[Math.floor((offset % 36) / 6)]}, ${levels[offset % 6]})`;
  }
  const gray = 8 + (value - 232) * 10;
  return `rgb(${gray}, ${gray}, ${gray})`;
}
