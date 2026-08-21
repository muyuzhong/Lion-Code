import React, { useState } from 'react';
import { Key, Server, Sliders, X } from 'lucide-react';
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
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-200 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-neutral-500" />
            <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              Provider & 模型设置
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 表单 */}
        <form onSubmit={handleSave} className="p-5 space-y-4 text-xs">
          {/* Provider 协议 */}
          <div>
            <label className="block font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
              API 协议类型
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setProvider('openai')}
                className={`py-2 px-3 rounded-lg border text-center font-medium transition-all ${
                  provider === 'openai'
                    ? 'border-neutral-900 dark:border-neutral-100 bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900'
                    : 'border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800'
                }`}
              >
                OpenAI Compatible
              </button>
              <button
                type="button"
                onClick={() => setProvider('anthropic')}
                className={`py-2 px-3 rounded-lg border text-center font-medium transition-all ${
                  provider === 'anthropic'
                    ? 'border-neutral-900 dark:border-neutral-100 bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900'
                    : 'border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800'
                }`}
              >
                Anthropic
              </button>
            </div>
          </div>

          {/* 模型名 */}
          <div>
            <label className="block font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
              模型名称 (Model)
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. gpt-4o, deepseek-chat, claude-3-5-sonnet"
              className="w-full px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-1 focus:ring-neutral-400"
            />
            {models.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {models.map((m) => (
                  <button
                    key={m.model}
                    type="button"
                    onClick={() => setModel(m.model)}
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 text-neutral-600 dark:text-neutral-300 transition-colors"
                  >
                    {m.model}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* API Key */}
          <div>
            <label className="block font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
              API Key (选填，不填保持不变)
            </label>
            <div className="relative">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full pl-8 pr-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-1 focus:ring-neutral-400"
              />
              <Key className="w-3.5 h-3.5 text-neutral-400 absolute left-2.5 top-2.5" />
            </div>
          </div>

          {/* Base URL */}
          <div>
            <label className="block font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
              API Base URL (选填)
            </label>
            <div className="relative">
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className="w-full pl-8 pr-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-1 focus:ring-neutral-400"
              />
              <Server className="w-3.5 h-3.5 text-neutral-400 absolute left-2.5 top-2.5" />
            </div>
          </div>

          {/* 底部保存按钮 */}
          <div className="pt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 font-medium transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="px-4 py-1.5 rounded-lg bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 font-medium shadow-sm hover:opacity-90 transition-all"
            >
              {isSaving ? '保存中...' : '保存配置'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
