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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs animate-in fade-in">
      <div className="flex w-full max-w-md flex-col rounded-2xl border border-border bg-card shadow-2xl text-card-foreground">
        <div className="flex items-center justify-between border-b border-border/60 px-6 py-4">
          <div className="flex items-center gap-2">
            <Settings className="size-4.5 text-primary" />
            <h3 className="text-sm font-semibold">服务与模型配置 (Settings)</h3>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-muted-foreground hover:bg-muted transition">
            <X className="size-4" />
          </button>
        </div>

        <form onSubmit={handleSave} className="p-6 space-y-4 text-xs">
          <div>
            <label className="font-medium text-foreground">API 协议格式 (Provider)</label>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setProvider("openai")}
                className={`flex items-center justify-center gap-1.5 rounded-lg border py-2 font-medium transition ${
                  provider === "openai"
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-muted-foreground hover:bg-muted"
                }`}
              >
                <span>OpenAI / DeepSeek</span>
              </button>
              <button
                type="button"
                onClick={() => setProvider("anthropic")}
                className={`flex items-center justify-center gap-1.5 rounded-lg border py-2 font-medium transition ${
                  provider === "anthropic"
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-muted-foreground hover:bg-muted"
                }`}
              >
                <span>Anthropic</span>
              </button>
            </div>
          </div>

          <div>
            <label className="font-medium text-foreground flex items-center gap-1.5">
              <Cpu className="size-3.5" /> 模型名称 (Model Name)
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. deepseek-chat, gpt-4o, claude-3-5-sonnet-20241022"
              className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-xs focus:outline-hidden focus:ring-1 focus:ring-primary"
            />
          </div>

          <div>
            <label className="font-medium text-foreground flex items-center gap-1.5">
              <Key className="size-3.5" /> API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-xs focus:outline-hidden focus:ring-1 focus:ring-primary font-mono"
            />
          </div>

          <div>
            <label className="font-medium text-foreground flex items-center gap-1.5">
              <Globe className="size-3.5" /> Base URL (可选)
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="e.g. https://api.deepseek.com/v1"
              className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-xs focus:outline-hidden focus:ring-1 focus:ring-primary font-mono"
            />
          </div>

          {status?.available_thinking_levels && (
            <div>
              <label className="font-medium text-foreground">深度思考档位 (Extended Thinking)</label>
              <div className="mt-1.5 flex gap-1.5">
                {status.available_thinking_levels.map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    onClick={() => setThinking(lvl)}
                    className={`flex-1 rounded-lg border py-1.5 text-center uppercase tracking-wider text-[11px] font-medium transition ${
                      thinking === lvl
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-card text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    {lvl}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="mt-6 flex items-center justify-end gap-2 pt-3 border-t border-border/60">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-4 py-2 text-xs text-muted-foreground hover:bg-muted transition"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:opacity-90 transition shadow-xs"
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
