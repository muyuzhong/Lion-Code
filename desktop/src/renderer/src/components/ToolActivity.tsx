import type { ReasoningMessagePartComponent, ToolCallMessagePartComponent } from "@assistant-ui/react";
import { Check, ChevronRight, Copy, Sparkles, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { Streamdown } from "streamdown";
import { parseAnsiToSpans, pickResultFormat } from "../toolPresentation";

export const ReasoningActivity: ReasoningMessagePartComponent = ({ text }) => (
  <details className="reasoning">
    <summary><Sparkles aria-hidden="true" size={15} /><span>思考</span><ChevronRight className="disclosure" aria-hidden="true" size={14} /></summary>
    <pre>{text}</pre>
  </details>
);

export const ToolActivity: ToolCallMessagePartComponent = ({ toolCallId, toolName, args, result, isError }) => {
  const [copied, setCopied] = useState(false);
  const text = result === undefined ? null : typeof result === "string" ? result : JSON.stringify(result, null, 2);
  const agentType = toolName === "agent" && args && typeof args === "object" && typeof Reflect.get(args, "type") === "string" ? String(Reflect.get(args, "type")) : "";
  const summary = toolName === "agent" && args && typeof args === "object" && typeof Reflect.get(args, "description") === "string"
    ? String(Reflect.get(args, "description"))
    : summarizeArgs(args);
  const state = result === undefined ? "running" : isError ? "error" : "done";
  const copyPayload = [JSON.stringify(args, null, 2), text].filter(Boolean).join("\n\n");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(copyPayload);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };
  return (
    <details className={`tool-row ${isError ? "tool-error" : ""}`} data-tool-call-id={toolCallId}>
      <summary className="tool-row-header">
        <span className="tool-row-icon" aria-hidden="true"><TerminalSquare size={14} /></span>
        <span className="tool-row-name">{toolName}</span>
        {agentType ? <span className="tool-row-agent">{agentType}</span> : null}
        {summary ? <span className="tool-row-summary">{summary}</span> : null}
        <span className={`tool-state ${state}`}><i aria-hidden="true" />{state === "running" ? "运行中" : state === "error" ? "失败" : "完成"}</span>
        <ChevronRight className="disclosure" aria-hidden="true" size={14} />
      </summary>
      <div className="tool-row-body">
        <button className={`tool-copy ${copied ? "copied" : ""}`} type="button" aria-label={copied ? "已复制工具详情" : "复制工具详情"} onClick={() => void copy()}>{copied ? <Check aria-hidden="true" size={13} /> : <Copy aria-hidden="true" size={13} />}</button>
        <section><span className="tool-section-label">输入</span><pre className="tool-arguments">{JSON.stringify(args, null, 2)}</pre></section>
        {text === null ? null : <section><span className="tool-section-label">结果</span><ToolResult toolName={toolName} text={text} isError={isError ?? false} /></section>}
      </div>
    </details>
  );
};

function summarizeArgs(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  for (const key of ["command", "path", "query", "pattern", "prompt"]) {
    const value = Reflect.get(args, key);
    if (typeof value === "string" && value.trim()) return value.replace(/\s+/g, " ").trim();
  }
  return "";
}

function ToolResult({ toolName, text, isError }: { toolName: string; text: string; isError: boolean }) {
  if (isError) return <pre>{text}</pre>;
  const format = pickResultFormat(toolName, text);
  if (format === "markdown") return <div className="tool-markdown"><Streamdown>{text}</Streamdown></div>;
  if (format === "ansi") return <pre className="terminal-result">{parseAnsiToSpans(text).map((span, index) => <span key={index} style={{ color: span.fg, backgroundColor: span.bg, fontWeight: span.bold ? 700 : undefined, fontStyle: span.italic ? "italic" : undefined, textDecoration: span.underline ? "underline" : undefined }}>{span.text}</span>)}</pre>;
  if (format === "diff") return <pre className="diff-result">{text.split("\n").map((line, index) => <span className={line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-remove" : line.startsWith("@@") ? "diff-hunk" : ""} key={index}>{line}{"\n"}</span>)}</pre>;
  return <pre>{text}</pre>;
}
