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
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-center justify-center p-4 select-none">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#161e31]/95 text-slate-100 shadow-2xl overflow-hidden backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#101524]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-xl bg-[#4e75ff]/15 text-[#4e75ff]">
              <Sliders className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-white">
              模型与 Provider 设置
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 表单 */}
        <form onSubmit={handleSave} className="p-6 space-y-4 text-xs">
          {/* Provider 协议卡片 */}
          <div>
            <label className="block font-medium text-slate-300 mb-2">
              接口协议类型 (Protocol)
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              <button
                type="button"
                onClick={() => setProvider('openai')}
                className={`py-2.5 px-3 rounded-2xl border text-center font-medium transition-all ${
                  provider === 'openai'
                    ? 'border-[#4e75ff] bg-[#4e75ff]/20 text-[#4e75ff] shadow-sm'
                    : 'border-white/10 bg-white/[0.03] text-slate-400 hover:bg-white/[0.06]'
                }`}
              >
                OpenAI Compatible
              </button>
              <button
                type="button"
                onClick={() => setProvider('anthropic')}
                className={`py-2.5 px-3 rounded-2xl border text-center font-medium transition-all ${
                  provider === 'anthropic'
                    ? 'border-[#4e75ff] bg-[#4e75ff]/20 text-[#4e75ff] shadow-sm'
                    : 'border-white/10 bg-white/[0.03] text-slate-400 hover:bg-white/[0.06]'
                }`}
              >
                Anthropic
              </button>
            </div>
          </div>

          {/* 模型名 */}
          <div>
            <label className="block font-medium text-slate-300 mb-1.5">
              模型名称 (Model)
            </label>
            <div className="relative">
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="e.g. deepseek-chat, gpt-4o, claude-3-5-sonnet"
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-[#0b0f19] text-white placeholder-slate-500 focus:outline-none focus:border-[#4e75ff]"
              />
              <Cpu className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            </div>

            {models.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {models.map((m) => (
                  <button
                    key={m.model}
                    type="button"
                    onClick={() => setModel(m.model)}
                    className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/[0.06] hover:bg-[#4e75ff]/20 text-slate-300 hover:text-[#4e75ff] border border-white/5 transition-colors"
                  >
                    {m.model}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* API Key */}
          <div>
            <label className="block font-medium text-slate-300 mb-1.5">
              API Key (选填，留空保持当前配置)
            </label>
            <div className="relative">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-[#0b0f19] text-white placeholder-slate-500 focus:outline-none focus:border-[#4e75ff]"
              />
              <Key className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            </div>
          </div>

          {/* Base URL */}
          <div>
            <label className="block font-medium text-slate-300 mb-1.5">
              API Base URL (选填)
            </label>
            <div className="relative">
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.deepseek.com/v1"
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-[#0b0f19] text-white placeholder-slate-500 focus:outline-none focus:border-[#4e75ff]"
              />
              <Server className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            </div>
          </div>

          {/* 底部保存按钮 */}
          <div className="pt-3 flex items-center justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 font-medium transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-[#4e75ff] to-[#3b82f6] hover:from-[#3d61f5] hover:to-[#2563eb] text-white font-medium shadow-lg shadow-blue-500/25 transition-all"
            >
              {isSaving ? '保存中...' : '保存配置'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
