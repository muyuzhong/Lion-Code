import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, Sparkles, User } from "lucide-react";
import { ChatMessage } from "@/types/chat";
import { ReasoningView } from "./ReasoningView";
import { ToolView } from "./ToolView";

interface MessageItemProps {
  message: ChatMessage;
}

function CodeBlock({ language, value }: { language: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative my-3 overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-950 font-mono text-xs shadow-xs">
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900/90 px-3 py-1.5 text-zinc-400">
        <span className="text-[11px] font-medium">{language || "text"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] hover:text-zinc-200 transition"
        >
          {copied ? <Check className="size-3 text-emerald-400" /> : <Copy className="size-3" />}
          <span>{copied ? "已复制" : "复制代码"}</span>
        </button>
      </div>
      <SyntaxHighlighter
        language={language || "text"}
        style={vscDarkPlus}
        customStyle={{
          margin: 0,
          padding: "0.85rem 1rem",
          background: "transparent",
          fontSize: "0.8rem",
          lineHeight: "1.5",
        }}
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end gap-3 px-4 py-3">
        <div className="max-w-2xl rounded-2xl bg-zinc-900 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-950 px-4 py-2.5 text-sm leading-relaxed shadow-sm">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <div className="flex size-7 shrink-0 select-none items-center justify-center rounded-full bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
          <User className="size-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 px-4 py-4 hover:bg-zinc-50/50 dark:hover:bg-zinc-900/20 transition">
      <div className="flex size-7 shrink-0 select-none items-center justify-center rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400">
        <Sparkles className="size-4" />
      </div>

      <div className="flex-1 min-w-0 text-sm leading-relaxed text-zinc-900 dark:text-zinc-100 space-y-2">
        {message.reasoning && (
          <ReasoningView reasoning={message.reasoning} isStreaming={message.isStreaming && !message.content} />
        )}

        {message.tools && message.tools.length > 0 && (
          <div className="space-y-1.5 my-2.5">
            {message.tools.map((tool) => (
              <ToolView key={tool.id} tool={tool} />
            ))}
          </div>
        )}

        {message.content ? (
          <div className="prose prose-sm dark:prose-invert max-w-none break-words text-zinc-900 dark:text-zinc-100">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ inline, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || "");
                  const codeString = String(children).replace(/\n$/, "");
                  return !inline && match ? (
                    <CodeBlock language={match[1]} value={codeString} />
                  ) : (
                    <code className="rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 font-mono text-[0.85em] text-zinc-900 dark:text-zinc-100" {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        ) : message.isStreaming ? (
          <div className="flex items-center gap-1.5 text-xs text-zinc-400 dark:text-zinc-500">
            <span className="size-1.5 rounded-full bg-blue-500 animate-pulse" />
            <span>Lion Code 正在思考输入...</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
