import React, { useState, useEffect, useCallback } from "react";
import { Sidebar } from "@/components/chat/Sidebar";
import { Header } from "@/components/chat/Header";
import { ChatArea } from "@/components/chat/ChatArea";
import { ChatInput } from "@/components/chat/ChatInput";
import { ConfirmBanner, PlanApprovalModal } from "@/components/chat/ApprovalModals";
import { SettingsModal } from "@/components/chat/SettingsModal";
import { useLionChat } from "@/hooks/useLionChat";
import { fetchSessions, fetchStatus, resumeSession, createNewSession, fetchModels, fetchSkills } from "@/lib/api";
import { ModelChoice, ServerStatus, SessionSummary, SkillItem } from "@/types/chat";
import { ThemeProvider } from "@/context/ThemeContext";
import { Toaster, toast } from "sonner";

function ChatApp() {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [models, setModels] = useState<ModelChoice[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [skills, setSkills] = useState<SkillItem[]>([]);
  // 用对象引用而非裸 string：重复点击同一 skill 时文案相同，靠每次新建对象触发 ChatInput 的填入 effect
  const [skillPrompt, setSkillPrompt] = useState<{ text: string } | null>(null);

  const {
    messages,
    isConnected,
    isStreaming,
    confirmRequest,
    planApprovalRequest,
    queue,
    runtimeNotice,
    metrics,
    sendMessage,
    sendFollowUp,
    sendSteer,
    sendCancel,
    respondConfirm,
    respondPlanApproval,
  } = useLionChat(currentSessionId);

  const loadData = useCallback(async () => {
    try {
      // skills 拉取失败静默降级为空列表，不阻塞其余面板数据
      const [statusData, sessionsData, modelsData, skillsData] = await Promise.all([
        fetchStatus().catch(() => null),
        fetchSessions().catch(() => []),
        fetchModels().catch(() => []),
        fetchSkills().catch(() => []),
      ]);
      if (statusData) {
        setStatus(statusData);
        if (!currentSessionId) {
          setCurrentSessionId(statusData.session_id);
        }
      }
      setSessions(sessionsData);
      setModels(modelsData);
      setSkills(skillsData);
    } catch (err) {
      console.error("Failed to load initial data:", err);
    }
  }, [currentSessionId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 会话尚无标题字段（P2-7 未落地），以 ID 截断作为标签页区分标识
  useEffect(() => {
    document.title = currentSessionId
      ? `Lion Code — ${currentSessionId.slice(0, 8)}`
      : "Lion Code — AI Coding Agent";
  }, [currentSessionId]);

  // D4：只填入自然句式引用，由用户补全意图后发送，不伪造"直接执行 skill"语义
  const handleSelectSkill = useCallback((name: string) => {
    setSkillPrompt({ text: `用 ${name} 技能帮我：` });
  }, []);

  const handleSelectSession = async (sessionId: string) => {
    try {
      await resumeSession(sessionId);
      setCurrentSessionId(sessionId);
      await loadData();
      toast.success("已切换到指定会话");
    } catch (err: any) {
      toast.error(err.message || "切换会话失败");
    }
  };

  const handleNewSession = async () => {
    try {
      const res = await createNewSession();
      setCurrentSessionId(res.session_id);
      await loadData();
      toast.success("已创建新会话");
    } catch (err: any) {
      toast.error(err.message || "创建新会话失败");
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 transition-colors">
      <Toaster position="top-right" richColors />

      {/* Left Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        status={status}
        skills={skills}
        onSelectSkill={handleSelectSkill}
      />

      {/* Main Content Area */}
      <main className="flex flex-1 flex-col overflow-hidden relative">
        {/* Top Header */}
        <Header
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          onNewChat={handleNewSession}
          onOpenSettings={() => setSettingsOpen(true)}
          status={status}
          models={models}
          onModelChanged={loadData}
          isConnected={isConnected}
        />

        {/* Message Stream Area */}
        <ChatArea
          messages={messages}
          queue={queue}
          onSelectPrompt={(text) => sendMessage(text)}
        />

        {/* Bottom Input Box */}
        <ChatInput
          onSendMessage={sendMessage}
          onFollowUp={sendFollowUp}
          onSteer={sendSteer}
          onCancel={sendCancel}
          isStreaming={isStreaming}
          disabled={!isConnected}
          queueCount={queue.steering.length + queue.followUp.length}
          runtimeNotice={runtimeNotice}
          metrics={metrics}
          prefill={skillPrompt}
        />

        {/* Action Confirm Banner */}
        <ConfirmBanner
          request={confirmRequest}
          onRespond={respondConfirm}
        />

        {/* Plan Approval Modal */}
        <PlanApprovalModal
          request={planApprovalRequest}
          onRespond={respondPlanApproval}
        />

        {/* Single Settings Modal */}
        <SettingsModal
          isOpen={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          status={status}
          onStatusUpdated={loadData}
        />
      </main>
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <ChatApp />
    </ThemeProvider>
  );
}

export default App;
