import React, { useEffect, useState } from 'react';
import {
  configureProvider,
  createNewSession,
  fetchModels,
  fetchSessions,
  fetchSkills,
  fetchStatus,
  resumeSession,
  setThinkingLevel,
} from './api/client';
import { ChatContainer } from './components/ChatContainer';
import { ChatInput } from './components/ChatInput';
import { ConfirmBanner } from './components/ConfirmBanner';
import { Dock } from './components/Dock';
import { Header } from './components/Header';
import { PlanApprovalDialog } from './components/PlanApprovalDialog';
import { SettingsModal } from './components/SettingsModal';
import { Sidebar } from './components/Sidebar';
import { useLionChat } from './hooks/useLionChat';
import { ModelChoice, ServerStatus, SessionSummary, SkillItem } from './types';

export const App: React.FC = () => {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [models, setModels] = useState<ModelChoice[]>([]);
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [activeTab, setActiveTab] = useState<'chat' | 'skills' | 'workspace'>('chat');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isDark, setIsDark] = useState(true);

  const {
    messages,
    isConnected,
    isGenerating,
    pendingConfirm,
    pendingPlanApproval,
    notices,
    sendPrompt,
    cancelGeneration,
    respondConfirm,
    respondPlanApproval,
    clearMessages,
  } = useLionChat(status?.sessionId);

  const loadInitialData = async () => {
    try {
      const [st, sess, mdls, sks] = await Promise.all([
        fetchStatus(),
        fetchSessions(),
        fetchModels(),
        fetchSkills(),
      ]);
      setStatus(st);
      setSessions(sess);
      setModels(mdls);
      setSkills(sks);
    } catch (err) {
      console.error('Failed to load initial data:', err);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, []);

  // 主题切换
  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDark]);

  const handleNewSession = async () => {
    try {
      const res = await createNewSession();
      if (res.success) {
        clearMessages();
        await loadInitialData();
      }
    } catch (err) {
      console.error('Failed to create new session:', err);
    }
  };

  const handleResumeSession = async (sessId: string) => {
    try {
      const res = await resumeSession(sessId);
      if (res.success) {
        clearMessages();
        await loadInitialData();
      }
    } catch (err) {
      console.error('Failed to resume session:', err);
    }
  };

  const handleModelSelect = async (newModel: string) => {
    try {
      await configureProvider({ model: newModel });
      await loadInitialData();
    } catch (err) {
      console.error('Failed to switch model:', err);
    }
  };

  const handleThinkingChange = async (level: string) => {
    try {
      const res = await setThinkingLevel(level);
      if (status) {
        setStatus({ ...status, thinkingLevel: res.thinking_level });
      }
    } catch (err) {
      console.error('Failed to change thinking level:', err);
    }
  };

  const handleSaveConfig = async (config: {
    model?: string;
    api_key?: string;
    provider?: 'openai' | 'anthropic';
    base_url?: string;
  }) => {
    try {
      await configureProvider(config);
      await loadInitialData();
    } catch (err) {
      console.error('Failed to save provider config:', err);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0b0f19] text-slate-100 font-sans">
      {/* 最左侧 DeepSeek Harness 图标 Dock */}
      <Dock
        activeTab={activeTab}
        onTabChange={(tab) => {
          setActiveTab(tab);
          if (!isSidebarOpen) setIsSidebarOpen(true);
        }}
        isSidebarOpen={isSidebarOpen}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        isDark={isDark}
        onToggleTheme={() => setIsDark(!isDark)}
      />

      {/* 会话与功能侧边栏 Drawer */}
      <Sidebar
        isOpen={isSidebarOpen}
        activeTab={activeTab}
        sessions={sessions}
        currentSessionId={status?.sessionId}
        cwd={status?.cwd}
        skills={skills}
        onNewSession={handleNewSession}
        onResumeSession={handleResumeSession}
        onSkillClick={(name) => sendPrompt(`/${name} `)}
      />

      {/* 主对话区 */}
      <div className="flex-1 flex flex-col min-w-0 h-full relative">
        {/* 顶部 Header */}
        <Header
          status={status}
          models={models}
          isConnected={isConnected}
          onModelSelect={handleModelSelect}
          onThinkingChange={handleThinkingChange}
          onClearChat={clearMessages}
        />

        {/* 聊天消息流 */}
        <ChatContainer
          messages={messages}
          onPromptClick={(text) => sendPrompt(text)}
        />

        {/* 底部悬浮输入框 */}
        <ChatInput
          onSend={(text) => sendPrompt(text)}
          onCancel={cancelGeneration}
          isGenerating={isGenerating}
          disabled={!isConnected}
          currentModel={status?.model}
          thinkingLevel={status?.thinkingLevel}
          onThinkingClick={() => {
            if (status?.availableThinkingLevels) {
              const currentIdx = status.availableThinkingLevels.indexOf(status.thinkingLevel);
              const nextIdx = (currentIdx + 1) % status.availableThinkingLevels.length;
              handleThinkingChange(status.availableThinkingLevels[nextIdx]);
            }
          }}
          onClearChat={clearMessages}
        />

        {/* 敏感操作确认浮窗 */}
        {pendingConfirm && (
          <ConfirmBanner
            request={pendingConfirm}
            onRespond={respondConfirm}
          />
        )}

        {/* Plan 审批确认弹窗 */}
        {pendingPlanApproval && (
          <PlanApprovalDialog
            request={pendingPlanApproval}
            onRespond={respondPlanApproval}
          />
        )}

        {/* 设置弹窗 */}
        <SettingsModal
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          models={models}
          currentModel={status?.model || ''}
          currentProvider={status?.providerName || 'openai'}
          onSave={handleSaveConfig}
        />

        {/* 浮动 Notice 提示 */}
        {notices.length > 0 && (
          <div className="fixed top-16 right-4 z-50 space-y-2 max-w-sm">
            {notices.map((n) => (
              <div
                key={n.id}
                className={`p-3 rounded-2xl text-xs shadow-2xl border backdrop-blur-xl animate-in fade-in slide-in-from-top-3 duration-200 ${
                  n.role === 'error'
                    ? 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                    : 'bg-neutral-900/90 border-white/10 text-white'
                }`}
              >
                {n.text}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
