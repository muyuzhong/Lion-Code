import React, { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy } from "lucide-react";

// Markdown 围栏代码块的统一呈现（MessageItem 与 agent 子任务卡片共用）
export function CodeBlock({ language, value }: { language: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative my-3 overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-950 font-mono text-xs shadow-xs">
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900/90 px-3.5 py-1.5 text-zinc-400">
        <span className="text-[11px] font-medium text-zinc-300">{language || "plaintext"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] hover:text-zinc-100 transition"
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
          lineHeight: "1.55",
        }}
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
}
