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

  const handleSelectModel = async (modelName: string) => {
    try {
      await configureProvider({ model: modelName });
      toast.success(`已切换模型至: ${modelName}`);
      onModelChanged();
      setIsOpen(false);
    } catch (err: any) {
      toast.error(err.message || "切换模型失败");
    }
  };

  // 默认备选模型列表，合并后端传来的已知模型
  const allModels = Array.from(
    new Set([
      currentModel,
      ...models.map((m) => m.model),
      "deepseek-chat",
      "deepseek-coder",
      "gpt-4o",
      "gpt-4o-mini",
      "claude-3-5-sonnet-20241022",
      "claude-3-5-haiku-20241022",
    ])
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
            {allModels.map((m) => {
              const isSelected = m === currentModel;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => handleSelectModel(m)}
                  className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left transition ${
                    isSelected
                      ? "bg-zinc-100 dark:bg-zinc-800 font-medium text-zinc-900 dark:text-zinc-100"
                      : "text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                  }`}
                >
                  <div className="flex items-center gap-2 truncate">
                    <Cpu className="size-3.5 shrink-0 opacity-60" />
                    <span className="truncate">{m}</span>
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
