import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { ToolCallItem } from "@/types/chat";
import { parseAnsiToSpans, pickResultFormat } from "@/lib/toolResultFormat";
import { CodeBlock } from "./CodeBlock";

// 工具执行结果的展示区：按 lib/toolResultFormat 的判定切 diff 高亮 /
// ANSI 终端卡片 / Markdown / 纯文本四态。判定逻辑是纯函数留在 lib，组件只渲染。

// 纯文本与错误共用的基础样式（与历史实现一致，保证未命中新形态的工具零回归）
const PLAIN_PRE_CLASS =
  "max-h-64 overflow-y-auto rounded-lg bg-zinc-950 p-2.5 whitespace-pre-wrap border border-zinc-800 font-mono text-[11px] leading-relaxed select-text";

export function ToolResultView({ tool }: { tool: ToolCallItem }) {
  const result = tool.result ?? "";

  // 错误原文固定纯文本红字：失败排查需要逐字对照，错误文本形态不受工具类型约束
  if (tool.status === "error") {
    return <pre className={`${PLAIN_PRE_CLASS} text-rose-400`}>{result}</pre>;
  }

  const format = pickResultFormat(tool.toolName, result);

  if (format === "diff") {
    // edit 类结果携带 unified diff（后端 _generate_diff），Prism 原生 diff 语法增绿删红
    return (
      <div className="max-h-64 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950">
        <SyntaxHighlighter
          language="diff"
          style={vscDarkPlus}
          wrapLongLines
          customStyle={{
            margin: 0,
            padding: "0.625rem",
            background: "transparent",
            fontSize: "11px",
            lineHeight: 1.65,
          }}
        >
          {result}
        </SyntaxHighlighter>
      </div>
    );
  }

  if (format === "ansi") {
    // 终端风格卡片：黑底等宽 + SGR 颜色；非 SGR 转义序列已在解析时剥离
    const spans = parseAnsiToSpans(result);
    return (
      <pre className={`${PLAIN_PRE_CLASS} text-zinc-300`}>
        {spans.map((span, i) => (
          <span
            key={i}
            style={{
              color: span.fg,
              backgroundColor: span.bg,
              fontWeight: span.bold ? 700 : undefined,
              fontStyle: span.italic ? "italic" : undefined,
              textDecoration: span.underline ? "underline" : undefined,
            }}
          >
            {span.text}
          </span>
        ))}
      </pre>
    );
  }

  if (format === "markdown") {
    // agent 子任务产出多为结构化报告，按 Markdown 渲染并与助手消息共用代码块样式；
    // 外层展开区是等宽小字号，这里显式回到正文排版
    return (
      <div className="max-h-64 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 font-sans text-sm leading-relaxed text-zinc-900 dark:text-zinc-100 prose prose-sm dark:prose-invert max-w-none break-words">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ inline, className, children, ...props }: any) {
              const match = /language-(\w+)/.exec(className || "");
              const codeString = String(children).replace(/\n$/, "");
              return !inline && match ? (
                <CodeBlock language={match[1]} value={codeString} />
              ) : (
                <code
                  className="rounded bg-zinc-100 dark:bg-zinc-800/90 px-1.5 py-0.5 font-mono text-[0.85em] text-zinc-900 dark:text-zinc-100 border border-zinc-200/60 dark:border-zinc-700/60"
                  {...props}
                >
                  {children}
                </code>
              );
            },
          }}
        >
          {result}
        </ReactMarkdown>
      </div>
    );
  }

  return <pre className={`${PLAIN_PRE_CLASS} text-zinc-300`}>{result}</pre>;
}
