import React, { useState, useEffect, useCallback } from "react";
import { Sidebar } from "@/components/chat/Sidebar";
import { Header } from "@/components/chat/Header";
import { ChatArea } from "@/components/chat/ChatArea";
import { ChatInput } from "@/components/chat/ChatInput";
import { ConfirmBanner, PlanApprovalModal } from "@/components/chat/ApprovalModals";
import { SettingsModal } from "@/components/chat/SettingsModal";
import { useLionChat } from "@/hooks/useLionChat";
import { fetchSessions, fetchStatus, resumeSession, createNewSession } from "@/lib/api";
import { ServerStatus, SessionSummary } from "@/types/chat";
import { Toaster, toast } from "sonner";

export function App() {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");

  const {
    messages,
    isConnected,
    isStreaming,
    confirmRequest,
    planApprovalRequest,
    sendMessage,
    sendCancel,
    respondConfirm,
    respondPlanApproval,
  } = useLionChat(currentSessionId);

  const loadStatusAndSessions = useCallback(async () => {
    try {
      const [statusData, sessionsData] = await Promise.all([
        fetchStatus().catch(() => null),
        fetchSessions().catch(() => []),
      ]);
      if (statusData) {
        setStatus(statusData);
        if (!currentSessionId) {
          setCurrentSessionId(statusData.session_id);
        }
      }
      setSessions(sessionsData);
    } catch (err) {
      console.error("Failed to load initial data:", err);
    }
  }, [currentSessionId]);

  useEffect(() => {
    loadStatusAndSessions();
  }, [loadStatusAndSessions]);

  const handleSelectSession = async (sessionId: string) => {
    try {
      await resumeSession(sessionId);
      setCurrentSessionId(sessionId);
      await loadStatusAndSessions();
      toast.success("已切换到指定会话");
    } catch (err: any) {
      toast.error(err.message || "切换会话失败");
    }
  };

  const handleNewSession = async () => {
    try {
      const res = await createNewSession();
      setCurrentSessionId(res.session_id);
      await loadStatusAndSessions();
      toast.success("已创建新会话");
    } catch (err: any) {
      toast.error(err.message || "创建新会话失败");
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Toaster position="top-right" richColors />

      {/* Left Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onOpenSettings={() => setSettingsOpen(true)}
        status={status}
      />

      {/* Main Content Area */}
      <main className="flex flex-1 flex-col overflow-hidden relative">
        {/* Top Header */}
        <Header
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          onNewChat={handleNewSession}
          onOpenSettings={() => setSettingsOpen(true)}
          status={status}
          isConnected={isConnected}
        />

        {/* Message Stream Area */}
        <ChatArea
          messages={messages}
          onSelectPrompt={(text) => sendMessage(text)}
        />

        {/* Bottom Input Box */}
        <ChatInput
          onSendMessage={sendMessage}
          onCancel={sendCancel}
          isStreaming={isStreaming}
          disabled={!isConnected}
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

        {/* Settings Modal */}
        <SettingsModal
          isOpen={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          status={status}
          onStatusUpdated={loadStatusAndSessions}
        />
      </main>
    </div>
  );
}

export default App;
