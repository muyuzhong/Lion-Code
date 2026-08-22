import React, { useState } from "react";
import { X, Settings, Key, Globe, Cpu, Check } from "lucide-react";
import { ServerStatus } from "@/types/chat";
import { configureProvider, setThinkingLevel } from "@/lib/api";
import { toast } from "sonner";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  status: ServerStatus | null;
  onStatusUpdated: () => void;
}

export function SettingsModal({ isOpen, onClose, status, onStatusUpdated }: SettingsModalProps) {
  const [provider, setProvider] = useState<"openai" | "anthropic">("openai");
  const [model, setModel] = useState<string>(status?.model || "deepseek-chat");
  const [apiKey, setApiKey] = useState<string>("");
  const [baseUrl, setBaseUrl] = useState<string>("");
  const [thinking, setThinking] = useState<string>(status?.thinking_level || "off");
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (apiKey.trim() || model.trim() || baseUrl.trim()) {
        await configureProvider({
          provider,
          model: model.trim() || undefined,
          api_key: apiKey.trim() || undefined,
          base_url: baseUrl.trim() || undefined,
        });
      }

      if (thinking !== status?.thinking_level) {
        await setThinkingLevel(thinking);
      }

      toast.success("配置已更新！");
      onStatusUpdated();
      onClose();
    } catch (err: any) {
      toast.error(err.message || "更新配置失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md animate-in fade-in">
      <div className="flex w-full max-w-md flex-col rounded-2xl border border-zinc-800 bg-zinc-900 shadow-2xl text-zinc-100">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          <div className="flex items-center gap-2">
            <Settings className="size-4.5 text-zinc-200" />
            <h3 className="text-sm font-semibold text-zinc-100">服务与模型配置 (Settings)</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 transition"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSave} className="p-6 space-y-4 text-xs">
          <div>
            <label className="font-medium text-zinc-200">API 协议格式 (Provider)</label>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setProvider("openai")}
                className={`flex items-center justify-center gap-1.5 rounded-lg border py-2 font-medium transition ${
                  provider === "openai"
                    ? "border-zinc-200 bg-zinc-100 text-zinc-950"
                    : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:bg-zinc-800/80 hover:text-zinc-200"
                }`}
              >
                <span>OpenAI / DeepSeek</span>
              </button>
              <button
                type="button"
                onClick={() => setProvider("anthropic")}
                className={`flex items-center justify-center gap-1.5 rounded-lg border py-2 font-medium transition ${
                  provider === "anthropic"
                    ? "border-zinc-200 bg-zinc-100 text-zinc-950"
                    : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:bg-zinc-800/80 hover:text-zinc-200"
                }`}
              >
                <span>Anthropic</span>
              </button>
            </div>
          </div>

          <div>
            <label className="font-medium text-zinc-200 flex items-center gap-1.5">
              <Cpu className="size-3.5" /> 模型名称 (Model Name)
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. deepseek-chat, gpt-4o, claude-3-5-sonnet-20241022"
              className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-hidden focus:ring-1 focus:ring-zinc-500"
            />
          </div>

          <div>
            <label className="font-medium text-zinc-200 flex items-center gap-1.5">
              <Key className="size-3.5" /> API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-hidden focus:ring-1 focus:ring-zinc-500 font-mono"
            />
          </div>

          <div>
            <label className="font-medium text-zinc-200 flex items-center gap-1.5">
              <Globe className="size-3.5" /> Base URL (可选)
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="e.g. https://api.deepseek.com/v1"
              className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-hidden focus:ring-1 focus:ring-zinc-500 font-mono"
            />
          </div>

          {status?.available_thinking_levels && (
            <div>
              <label className="font-medium text-zinc-200">深度思考档位 (Extended Thinking)</label>
              <div className="mt-1.5 flex gap-1.5">
                {status.available_thinking_levels.map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    onClick={() => setThinking(lvl)}
                    className={`flex-1 rounded-lg border py-1.5 text-center uppercase tracking-wider text-[11px] font-medium transition ${
                      thinking === lvl
                        ? "border-zinc-200 bg-zinc-100 text-zinc-950"
                        : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:bg-zinc-800/80 hover:text-zinc-200"
                    }`}
                  >
                    {lvl}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="mt-6 flex items-center justify-end gap-2 pt-3 border-t border-zinc-800">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-zinc-800 px-4 py-2 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 transition"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 rounded-lg bg-zinc-100 text-zinc-950 px-4 py-2 text-xs font-medium hover:bg-zinc-200 transition shadow-xs"
            >
              <Check className="size-3.5" />
              <span>{saving ? "保存中..." : "保存配置"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
