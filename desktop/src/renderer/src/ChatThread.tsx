import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  unstable_useComposerInput,
  type ReasoningMessagePartComponent,
  type TextMessagePartComponent,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { Streamdown } from "streamdown";
import { useEffect, useRef, useState } from "react";
import { formatRunDuration } from "../../shared/chat";
import { useLionRuntime } from "./assistantRuntime";

const MarkdownText: TextMessagePartComponent = ({ text }) => <Streamdown>{text}</Streamdown>;
const Reasoning: ReasoningMessagePartComponent = ({ text }) => (
  <details className="reasoning"><summary><span className="state-glyph thinking" aria-hidden="true" /> 推理过程</summary><pre>{text}</pre></details>
);
const Tool: ToolCallMessagePartComponent = ({ toolCallId, toolName, args, result, isError }) => (
  <details className={`tool ${isError ? "tool-error" : ""}`} data-tool-call-id={toolCallId}>
    <summary><span className={`state-glyph ${result === undefined ? "running" : isError ? "error" : "complete"}`} aria-hidden="true" /> {toolName}<small>{result === undefined ? "运行中" : isError ? "失败" : "完成"}</small></summary>
    <pre>{JSON.stringify(args, null, 2)}</pre>
    {result === undefined ? null : <pre>{typeof result === "string" ? result : JSON.stringify(result, null, 2)}</pre>}
  </details>
);
const partComponents = { Text: MarkdownText, Reasoning, tools: { Fallback: Tool } };

function UserMessage() {
  return <MessagePrimitive.Root className="message user-message"><MessagePrimitive.Parts components={partComponents} /></MessagePrimitive.Root>;
}

function AssistantMessage() {
  return <MessagePrimitive.Root className="message assistant-message"><MessagePrimitive.Parts components={partComponents} /><MessagePrimitive.Error><p className="message-error">生成未完成。检查连接后重试。</p></MessagePrimitive.Error></MessagePrimitive.Root>;
}

const messageComponents = { UserMessage, AssistantMessage };

export function ChatThread({ workspaceName, sidebarCollapsed, onToggleSidebar, onOpenSettings, skillPrompt }: {
  workspaceName: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onOpenSettings: () => void;
  skillPrompt: { key: number; text: string } | null;
}) {
  const { adapter, snapshot } = useLionRuntime();
  const [queuedText, setQueuedText] = useState("");
  const composer = unstable_useComposerInput();
  const { protocol } = snapshot;
  const queueCount = protocol.queue.steering.length + protocol.queue.followUp.length;

  useEffect(() => {
    if (!skillPrompt) return;
    composer.setText(skillPrompt.text);
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[aria-label="消息"]')?.focus());
  }, [skillPrompt?.key]);

  return (
    <main id="lion-thread" className="chat-shell" role="region" aria-label="Lion 聊天" data-message-count={protocol.messages.length}>
      <header className="chat-header">
        <div className="header-leading"><button className="icon-button sidebar-toggle" type="button" aria-label={sidebarCollapsed ? "展开侧栏" : "折叠侧栏"} onClick={onToggleSidebar}>☰</button><div><h1>{workspaceName}</h1><p>{snapshot.status?.model ?? "正在读取模型"} · {snapshot.status?.permission_mode ?? "权限未知"}</p></div></div>
        <div className="header-actions"><span className={`transport ${snapshot.transportStatus}`}><i aria-hidden="true" />{transportLabel(snapshot.transportStatus)}</span><button className="icon-button" type="button" aria-label="打开设置" onClick={onOpenSettings}>⚙</button></div>
      </header>
      {snapshot.transportError ? <p className="transport-error" role="alert">{snapshot.transportError}</p> : null}
      {snapshot.metadataError ? <p className="transport-error" role="alert">工作区信息未同步：{snapshot.metadataError}</p> : null}
      <ThreadPrimitive.Root className="thread-root">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.Empty><div className="empty-thread"><span className="empty-coordinate">{workspaceName.toUpperCase()} / READY</span><h2>把意图说清楚，Lion 会处理余下的路径。</h2><p>描述要完成的改动、需要核查的问题，或从左侧选择一个 Skill 开始。</p></div></ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={messageComponents} />
          <ThreadPrimitive.ViewportFooter className="thread-footer">
            {protocol.runtimeNotice ? <p className="runtime-notice">{runtimeNoticeText(protocol.runtimeNotice)}</p> : null}
            {queueCount > 0 ? <p className="queue-count">已排队 ×{queueCount} · {protocol.queue.steering.length > 0 ? "包含立即转向" : "将在当前任务后继续"}</p> : null}
            {protocol.isStreaming ? <div className="run-metrics" aria-label="当前运行统计"><span>{protocol.metrics.steps} 步</span><span>LLM {formatRunDuration(protocol.metrics.llmMs)}</span><span>工具 {formatRunDuration(protocol.metrics.toolMs)}</span></div> : null}
            {protocol.isStreaming ? (
              <div className="queue-controls">
                <label><span className="sr-only">追加运行指令</span><input value={queuedText} onChange={(event) => setQueuedText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && adapter.sendFollowUp(queuedText)) { event.preventDefault(); setQueuedText(""); } }} placeholder="追加指令；Enter 排队" /></label>
                <button type="button" className="button-quiet" onClick={() => { if (adapter.sendSteer(queuedText)) setQueuedText(""); }}>立即转向</button>
                <button type="button" onClick={() => { if (adapter.sendFollowUp(queuedText)) setQueuedText(""); }}>排队</button>
              </div>
            ) : null}
            <ComposerPrimitive.Root className="composer">
              <ComposerPrimitive.Input placeholder="给 Lion 一个任务…" aria-label="消息" />
              <ComposerPrimitive.Send>发送</ComposerPrimitive.Send>
              <ComposerPrimitive.Cancel>停止</ComposerPrimitive.Cancel>
            </ComposerPrimitive.Root>
            {!protocol.isStreaming ? <div className="chat-actions"><span>Enter 发送 · Shift+Enter 换行</span><div><button type="button" className="button-quiet" onClick={() => adapter.sendInput("")}>继续</button><button type="button" className="button-quiet" onClick={() => adapter.compact()}>压缩上下文</button></div></div> : null}
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
      {protocol.confirmRequest ? <Confirmation request={protocol.confirmRequest.message} approve={(approved) => adapter.respondConfirm(protocol.confirmRequest!.requestId, approved)} /> : null}
      {protocol.planApprovalRequest ? <PlanApproval plan={protocol.planApprovalRequest.plan} respond={(choice) => adapter.respondPlanApproval(protocol.planApprovalRequest!.requestId, choice)} /> : null}
    </main>
  );
}

function Confirmation({ request, approve }: { request: string; approve: (approved: boolean) => void }) {
  const safeAction = useRef<HTMLButtonElement>(null);
  useEffect(() => safeAction.current?.focus(), []);
  return <dialog className="approval" open aria-labelledby="confirm-title" onCancel={(event) => { event.preventDefault(); approve(false); }}><span className="workspace-kicker">需要确认</span><h2 id="confirm-title">允许这项操作？</h2><p>{request}</p><div><button ref={safeAction} onClick={() => approve(false)} className="button-quiet">保持阻止</button><button onClick={() => approve(true)}>允许一次</button></div></dialog>;
}

function PlanApproval({ plan, respond }: { plan: string; respond: (choice: "clear-and-execute" | "execute" | "manual-execute" | "keep-planning") => void }) {
  const safeAction = useRef<HTMLButtonElement>(null);
  useEffect(() => safeAction.current?.focus(), []);
  return <dialog className="approval plan-approval" open aria-labelledby="plan-title" onCancel={(event) => { event.preventDefault(); respond("keep-planning"); }}><span className="workspace-kicker">执行计划</span><h2 id="plan-title">选择下一步</h2><pre>{plan}</pre><div><button ref={safeAction} onClick={() => respond("keep-planning")} className="button-quiet">继续规划</button><button onClick={() => respond("manual-execute")} className="button-quiet">我来执行</button><button onClick={() => respond("execute")}>按计划执行</button><button onClick={() => respond("clear-and-execute")}>清空上下文后执行</button></div></dialog>;
}

function transportLabel(status: string): string {
  return ({ idle: "未连接", loading: "加载历史", connected: "已连接", reconnecting: "正在重连", error: "连接错误", closed: "已关闭" } as Record<string, string>)[status] ?? status;
}

function runtimeNoticeText(notice: { kind: "retry"; attempt: number; maxAttempts: number; delayMs: number; errorMessage: string } | { kind: "compaction"; reason: string }): string {
  return notice.kind === "retry" ? `正在重试 ${notice.attempt}/${notice.maxAttempts}（${Math.round(notice.delayMs / 1000)}s）· ${notice.errorMessage}` : `正在压缩上下文（${notice.reason}）`;
}
