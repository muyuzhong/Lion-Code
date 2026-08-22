import React, { useState, useRef, useEffect } from "react";
import { Sparkles, ChevronDown, Check, Cpu } from "lucide-react";
import { ModelChoice, ServerStatus } from "@/types/chat";
import { configureProvider } from "@/lib/api";
import { toast } from "sonner";

interface ModelSelectorDropdownProps {
  status: ServerStatus | null;
  models: ModelChoice[];
  onModelChanged: () => void;
}

export function ModelSelectorDropdown({ status, models, onModelChanged }: ModelSelectorDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const currentModel = status?.model || "deepseek-chat";
  const currentProvider: "openai" | "anthropic" =
    status?.provider_name === "anthropic" ? "anthropic" : "openai";

  // 选择项保留 provider/model 配对；跨 provider 的选择必须一并提交 provider，
  // 否则后端会在当前 provider 上找不到该模型。
  const handleSelectModel = async (choice: { provider: "openai" | "anthropic"; model: string }) => {
    try {
      await configureProvider(
        choice.provider === currentProvider
          ? { model: choice.model }
          : { model: choice.model, provider: choice.provider }
      );
      toast.success(`已切换模型至: ${choice.model}`);
      onModelChanged();
      setIsOpen(false);
    } catch (err: any) {
      toast.error(err.message || "切换模型失败");
    }
  };

  // 默认备选模型列表，合并后端传来的已知模型（按 provider/model 去重）
  const allChoices = Array.from(
    new Map(
      [
        { provider: currentProvider, model: currentModel },
        ...models.map((m) => ({
          provider: (m.provider_name === "anthropic" ? "anthropic" : "openai") as
            | "openai"
            | "anthropic",
          model: m.model,
        })),
        { provider: "openai" as const, model: "deepseek-chat" },
        { provider: "openai" as const, model: "deepseek-coder" },
        { provider: "openai" as const, model: "gpt-4o" },
        { provider: "openai" as const, model: "gpt-4o-mini" },
        { provider: "anthropic" as const, model: "claude-3-5-sonnet-20241022" },
        { provider: "anthropic" as const, model: "claude-3-5-haiku-20241022" },
      ].map((c) => [`${c.provider}/${c.model}`, c])
    ).values()
  );

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/90 px-2.5 py-1 text-xs font-semibold text-zinc-900 dark:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition shadow-2xs"
      >
        <Sparkles className="size-3.5 text-blue-600 dark:text-blue-400" />
        <span className="max-w-[140px] sm:max-w-[180px] truncate">{currentModel}</span>
        <ChevronDown className="size-3 text-zinc-400 dark:text-zinc-500" />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 z-50 mt-1.5 w-64 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-1.5 shadow-xl text-xs animate-in fade-in slide-in-from-top-1">
          <div className="px-2.5 py-1 text-[10px] font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">
            快速切换模型 (Switch Model)
          </div>
          <div className="max-h-56 overflow-y-auto space-y-0.5 mt-1">
            {allChoices.map((c) => {
              const isSelected = c.model === currentModel && c.provider === currentProvider;
              return (
                <button
                  key={`${c.provider}/${c.model}`}
                  type="button"
                  onClick={() => handleSelectModel(c)}
                  className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left transition ${
                    isSelected
                      ? "bg-zinc-100 dark:bg-zinc-800 font-medium text-zinc-900 dark:text-zinc-100"
                      : "text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                  }`}
                >
                  <div className="flex items-center gap-2 truncate">
                    <Cpu className="size-3.5 shrink-0 opacity-60" />
                    <span className="truncate">{c.model}</span>
                    {c.provider !== currentProvider && (
                      <span className="shrink-0 rounded border border-zinc-200 dark:border-zinc-700 px-1 text-[9px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                        {c.provider}
                      </span>
                    )}
                  </div>
                  {isSelected && <Check className="size-3.5 text-blue-600 dark:text-blue-400 shrink-0" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
