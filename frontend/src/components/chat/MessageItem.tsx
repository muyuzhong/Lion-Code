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
    <div className="relative my-3 overflow-hidden rounded-lg border border-border/80 bg-zinc-950 font-mono text-xs">
      <div className="flex items-center justify-between border-b border-border/40 bg-zinc-900/90 px-3 py-1.5 text-zinc-400">
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
        <div className="max-w-2xl rounded-2xl bg-primary px-4 py-2.5 text-primary-foreground text-sm leading-relaxed shadow-sm">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <div className="flex size-7 shrink-0 select-none items-center justify-center rounded-full bg-muted text-muted-foreground">
          <User className="size-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 px-4 py-4 hover:bg-muted/10 transition">
      <div className="flex size-7 shrink-0 select-none items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="size-4" />
      </div>

      <div className="flex-1 min-w-0 text-sm leading-relaxed text-foreground space-y-2">
        {message.reasoning && (
          <ReasoningView reasoning={message.reasoning} isStreaming={message.isStreaming && !message.content} />
        )}

        {message.tools && message.tools.length > 0 && (
          <div className="space-y-1 my-2">
            {message.tools.map((tool) => (
              <ToolView key={tool.id} tool={tool} />
            ))}
          </div>
        )}

        {message.content ? (
          <div className="prose prose-sm dark:prose-invert max-w-none break-words">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ inline, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || "");
                  const codeString = String(children).replace(/\n$/, "");
                  return !inline && match ? (
                    <CodeBlock language={match[1]} value={codeString} />
                  ) : (
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground" {...props}>
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
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="size-1.5 rounded-full bg-primary animate-pulse" />
            <span>Lion Code 正在输入...</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
