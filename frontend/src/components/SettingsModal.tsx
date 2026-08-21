import React, { useState } from 'react';
import { Cpu, Key, Server, Sliders, X } from 'lucide-react';
import { ModelChoice } from '../types';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  models: ModelChoice[];
  currentModel: string;
  currentProvider: string;
  onSave: (config: {
    model?: string;
    api_key?: string;
    provider?: 'openai' | 'anthropic';
    base_url?: string;
  }) => Promise<void>;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  models,
  currentModel,
  currentProvider,
  onSave,
}) => {
  const [model, setModel] = useState(currentModel);
  const [provider, setProvider] = useState<'openai' | 'anthropic'>(
    currentProvider === 'anthropic' ? 'anthropic' : 'openai'
  );
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  if (!isOpen) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await onSave({
        model: model.trim() || undefined,
        provider,
        api_key: apiKey.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
      });
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-md flex items-center justify-center p-4 select-none">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-neutral-900/90 text-neutral-100 shadow-2xl overflow-hidden backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-white/[0.02]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-xl bg-purple-500/10 text-purple-400">
              <Sliders className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-white">
              模型与 Provider 设置
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-neutral-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 表单 */}
        <form onSubmit={handleSave} className="p-6 space-y-4 text-xs">
          {/* Provider 协议卡片 */}
          <div>
            <label className="block font-medium text-neutral-300 mb-2">
              接口协议类型 (Protocol)
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              <button
                type="button"
                onClick={() => setProvider('openai')}
                className={`py-2.5 px-3 rounded-2xl border text-center font-medium transition-all ${
                  provider === 'openai'
                    ? 'border-purple-500/80 bg-purple-500/20 text-purple-300 shadow-sm'
                    : 'border-white/10 bg-white/[0.03] text-neutral-400 hover:bg-white/[0.06]'
                }`}
              >
                OpenAI Compatible
              </button>
              <button
                type="button"
                onClick={() => setProvider('anthropic')}
                className={`py-2.5 px-3 rounded-2xl border text-center font-medium transition-all ${
                  provider === 'anthropic'
                    ? 'border-purple-500/80 bg-purple-500/20 text-purple-300 shadow-sm'
                    : 'border-white/10 bg-white/[0.03] text-neutral-400 hover:bg-white/[0.06]'
                }`}
              >
                Anthropic
              </button>
            </div>
          </div>

          {/* 模型名 */}
          <div>
            <label className="block font-medium text-neutral-300 mb-1.5">
              模型名称 (Model)
            </label>
            <div className="relative">
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="e.g. gpt-4o, deepseek-chat, claude-3-5-sonnet"
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-black/40 text-white placeholder-neutral-500 focus:outline-none focus:border-purple-500"
              />
              <Cpu className="w-4 h-4 text-neutral-400 absolute left-3 top-2.5" />
            </div>

            {models.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {models.map((m) => (
                  <button
                    key={m.model}
                    type="button"
                    onClick={() => setModel(m.model)}
                    className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/[0.06] hover:bg-purple-500/20 text-neutral-300 hover:text-purple-300 border border-white/5 transition-colors"
                  >
                    {m.model}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* API Key */}
          <div>
            <label className="block font-medium text-neutral-300 mb-1.5">
              API Key (选填，留空保持当前配置)
            </label>
            <div className="relative">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-black/40 text-white placeholder-neutral-500 focus:outline-none focus:border-purple-500"
              />
              <Key className="w-4 h-4 text-neutral-400 absolute left-3 top-2.5" />
            </div>
          </div>

          {/* Base URL */}
          <div>
            <label className="block font-medium text-neutral-300 mb-1.5">
              API Base URL (选填)
            </label>
            <div className="relative">
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-black/40 text-white placeholder-neutral-500 focus:outline-none focus:border-purple-500"
              />
              <Server className="w-4 h-4 text-neutral-400 absolute left-3 top-2.5" />
            </div>
          </div>

          {/* 底部保存按钮 */}
          <div className="pt-3 flex items-center justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-neutral-400 hover:text-white hover:bg-white/10 font-medium transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-medium shadow-lg shadow-purple-500/25 transition-all"
            >
              {isSaving ? '保存中...' : '保存配置'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
