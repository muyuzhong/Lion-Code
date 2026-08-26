import {
  ActionBarPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  unstable_useComposerInput,
  type TextMessagePartComponent,
} from "@assistant-ui/react";
import { Copy } from "lucide-react";
import { Streamdown } from "streamdown";
import { useEffect, useState } from "react";
import { formatRunDuration } from "../../shared/chat";
import { useLionRuntime } from "./assistantRuntime";
import { ConfirmationSurface, PlanApprovalSurface } from "./components/ApprovalSurface";
import { ComposerChrome } from "./components/ComposerChrome";
import { ConversationTopbar } from "./components/ConversationTopbar";
import { ReasoningActivity, ToolActivity } from "./components/ToolActivity";
import type { SkillSummary } from "./backend";

const MarkdownText: TextMessagePartComponent = ({ text }) => <Streamdown>{text}</Streamdown>;
const partComponents = { Text: MarkdownText, Reasoning: ReasoningActivity, tools: { Fallback: ToolActivity } };

function UserMessage() {
  return <MessagePrimitive.Root className="message user-message"><div className="message-body"><MessagePrimitive.Parts components={partComponents} /></div><MessageActions /></MessagePrimitive.Root>;
}

function AssistantMessage() {
  return <MessagePrimitive.Root className="message assistant-message"><div className="message-body"><MessagePrimitive.Parts components={partComponents} /><MessagePrimitive.Error><p className="message-error">生成未完成。检查连接后重试。</p></MessagePrimitive.Error></div><MessageActions /></MessagePrimitive.Root>;
}

function MessageActions() {
  return <ActionBarPrimitive.Root className="message-actions" hideWhenRunning autohide="always"><ActionBarPrimitive.Copy className="message-action" aria-label="复制消息" title="复制消息"><Copy aria-hidden="true" size={13} /></ActionBarPrimitive.Copy></ActionBarPrimitive.Root>;
}

const messageComponents = { UserMessage, AssistantMessage };

export function ChatThread({ sidebarCollapsed, onToggleSidebar, onCreateSession, onOpenSearch, onOpenSettings, skills, skillPrompt }: {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onCreateSession: () => void;
  onOpenSearch: () => void;
  onOpenSettings: () => void;
  skills: SkillSummary[];
  skillPrompt: { key: number; text: string } | null;
}) {
  const { adapter, snapshot } = useLionRuntime();
  const [queuedText, setQueuedText] = useState("");
  const composer = unstable_useComposerInput();
  const { protocol } = snapshot;
  const queueCount = protocol.queue.steering.length + protocol.queue.followUp.length;
  const activeSession = snapshot.sessions.find((session) => session.id === snapshot.status?.session_id);
  const sessionTitle = activeSession?.label || snapshot.status?.session_id?.slice(0, 18) || "新建任务";

  useEffect(() => {
    if (!skillPrompt) return;
    composer.setText(skillPrompt.text);
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[aria-label="消息"]')?.focus());
  }, [skillPrompt?.key]);

  const steer = () => {
    if (adapter.sendSteer(queuedText)) setQueuedText("");
  };
  const followUp = () => {
    if (adapter.sendFollowUp(queuedText)) setQueuedText("");
  };

  return (
    <main id="lion-thread" className="chat-shell" role="region" aria-label="Lion 聊天" data-message-count={protocol.messages.length}>
      <ConversationTopbar
        title={sessionTitle}
        transportStatus={snapshot.transportStatus}
        transportLabel={transportLabel(snapshot.transportStatus)}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={onToggleSidebar}
        onCreateSession={onCreateSession}
        onOpenSearch={onOpenSearch}
      />
      <div className="chat-notices">
        {snapshot.transportError ? <p className="transport-error" role="alert">{snapshot.transportError}</p> : null}
        {snapshot.metadataError ? <p className="transport-error" role="alert">工作区信息未同步：{snapshot.metadataError}</p> : null}
      </div>
      <ThreadPrimitive.Root className="thread-root">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.Empty>
            <div className="empty-thread"><h2>准备好开始工作</h2><p>在下方输入任务，或从左侧选择已有会话。</p></div>
          </ThreadPrimitive.Empty>
          <div className="thread-content"><ThreadPrimitive.Messages components={messageComponents} /></div>
          <ThreadPrimitive.ViewportFooter className="composer-dock">
            <div className="composer-stack">
              <ComposerChrome
                isStreaming={protocol.isStreaming}
                queuedText={queuedText}
                queueCount={queueCount}
                hasSteering={protocol.queue.steering.length > 0}
                runtimeNotice={protocol.runtimeNotice ? runtimeNoticeText(protocol.runtimeNotice) : null}
                metrics={{ steps: protocol.metrics.steps, llm: formatRunDuration(protocol.metrics.llmMs), tools: formatRunDuration(protocol.metrics.toolMs) }}
                model={snapshot.status?.model ?? "正在读取模型"}
                permissionMode={snapshot.status?.permission_mode ?? "权限未知"}
                thinkingLevel={snapshot.status?.thinking_level ?? "medium"}
                skills={skills}
                onOpenSettings={onOpenSettings}
                onQueuedTextChange={setQueuedText}
                onSteer={steer}
                onFollowUp={followUp}
                onContinue={() => adapter.sendInput("")}
                onCompact={() => adapter.compact()}
              />
            </div>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
      {protocol.confirmRequest ? <ConfirmationSurface request={protocol.confirmRequest.message} approve={(approved) => adapter.respondConfirm(protocol.confirmRequest!.requestId, approved)} /> : null}
      {protocol.planApprovalRequest ? <PlanApprovalSurface plan={protocol.planApprovalRequest.plan} respond={(choice) => adapter.respondPlanApproval(protocol.planApprovalRequest!.requestId, choice)} /> : null}
    </main>
  );
}

function runtimeNoticeText(notice: { kind: "retry"; attempt: number; maxAttempts: number; delayMs: number; errorMessage: string } | { kind: "compaction"; reason: string }): string {
  return notice.kind === "retry" ? `正在重试 ${notice.attempt}/${notice.maxAttempts}（${Math.round(notice.delayMs / 1000)}s）· ${notice.errorMessage}` : `正在压缩上下文（${notice.reason}）`;
}

function transportLabel(status: string): string {
  return ({ idle: "未连接", loading: "加载历史", connected: "已连接", reconnecting: "正在重连", error: "连接错误", closed: "已关闭" } as Record<string, string>)[status] ?? status;
}
