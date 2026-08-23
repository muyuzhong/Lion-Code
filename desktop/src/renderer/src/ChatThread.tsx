import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  type ReasoningMessagePartComponent,
  type TextMessagePartComponent,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { Streamdown } from "streamdown";
import { useState } from "react";
import { useLionRuntime } from "./assistantRuntime";

const MarkdownText: TextMessagePartComponent = ({ text }) => <Streamdown>{text}</Streamdown>;
const Reasoning: ReasoningMessagePartComponent = ({ text }) => (
  <details className="reasoning"><summary>思考过程</summary><pre>{text}</pre></details>
);
const Tool: ToolCallMessagePartComponent = ({ toolCallId, toolName, args, result, isError }) => (
  <details className={`tool ${isError ? "tool-error" : ""}`} data-tool-call-id={toolCallId}>
    <summary>{toolName} · {result === undefined ? "运行中" : isError ? "失败" : "完成"}</summary>
    <pre>{JSON.stringify(args, null, 2)}</pre>
    {result === undefined ? null : <pre>{typeof result === "string" ? result : JSON.stringify(result, null, 2)}</pre>}
  </details>
);
const partComponents = { Text: MarkdownText, Reasoning, tools: { Fallback: Tool } };

function UserMessage() {
  return <MessagePrimitive.Root className="message user-message"><MessagePrimitive.Parts components={partComponents} /></MessagePrimitive.Root>;
}

function AssistantMessage() {
  return <MessagePrimitive.Root className="message assistant-message"><MessagePrimitive.Parts components={partComponents} /><MessagePrimitive.Error><p className="message-error">生成失败</p></MessagePrimitive.Error></MessagePrimitive.Root>;
}

const messageComponents = { UserMessage, AssistantMessage };

export function ChatThread() {
  const { adapter, snapshot } = useLionRuntime();
  const [queuedText, setQueuedText] = useState("");
  const { protocol } = snapshot;
  const queueCount = protocol.queue.steering.length + protocol.queue.followUp.length;

  return (
    <section className="chat-shell" aria-label="Lion 聊天" data-message-count={protocol.messages.length}>
      <header className="chat-header">
        <div><p className="eyebrow">LION DESKTOP</p><h1>工作区对话</h1></div>
        <span className={`transport ${snapshot.transportStatus}`}>{transportLabel(snapshot.transportStatus)}</span>
      </header>
      {snapshot.transportError ? <p className="transport-error" role="alert">{snapshot.transportError}</p> : null}
      <ThreadPrimitive.Root className="thread-root">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.Empty><p className="empty-thread">开始一段新的对话。</p></ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={messageComponents} />
          <ThreadPrimitive.ViewportFooter className="thread-footer">
            {protocol.runtimeNotice ? <p className="runtime-notice">{runtimeNoticeText(protocol.runtimeNotice)}</p> : null}
            {queueCount > 0 ? <p className="queue-count">已排队 ×{queueCount}</p> : null}
            {protocol.isStreaming ? (
              <div className="queue-controls">
                <input value={queuedText} onChange={(event) => setQueuedText(event.target.value)} placeholder="追加运行指令" />
                <button type="button" className="secondary" onClick={() => { if (adapter.sendSteer(queuedText)) setQueuedText(""); }}>立即转向</button>
                <button type="button" onClick={() => { if (adapter.sendFollowUp(queuedText)) setQueuedText(""); }}>排队</button>
              </div>
            ) : null}
            <ComposerPrimitive.Root className="composer">
              <ComposerPrimitive.Input placeholder="给 Lion 一个任务…" aria-label="消息" />
              <ComposerPrimitive.Send>发送</ComposerPrimitive.Send>
              <ComposerPrimitive.Cancel>停止</ComposerPrimitive.Cancel>
            </ComposerPrimitive.Root>
            {!protocol.isStreaming ? <div className="chat-actions"><button type="button" className="secondary" onClick={() => adapter.sendInput("")}>继续</button><button type="button" className="secondary" onClick={() => adapter.compact()}>压缩上下文</button></div> : null}
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
      {protocol.confirmRequest ? <Confirmation request={protocol.confirmRequest.message} approve={(approved) => adapter.respondConfirm(protocol.confirmRequest!.requestId, approved)} /> : null}
      {protocol.planApprovalRequest ? <PlanApproval plan={protocol.planApprovalRequest.plan} respond={(choice) => adapter.respondPlanApproval(protocol.planApprovalRequest!.requestId, choice)} /> : null}
    </section>
  );
}

function Confirmation({ request, approve }: { request: string; approve: (approved: boolean) => void }) {
  return <div className="approval" role="dialog" aria-modal="true"><p>{request}</p><div><button onClick={() => approve(false)} className="secondary">拒绝</button><button onClick={() => approve(true)}>允许</button></div></div>;
}

function PlanApproval({ plan, respond }: { plan: string; respond: (choice: "clear-and-execute" | "execute" | "manual-execute" | "keep-planning") => void }) {
  return <div className="approval" role="dialog" aria-modal="true"><pre>{plan}</pre><div><button onClick={() => respond("keep-planning")} className="secondary">继续规划</button><button onClick={() => respond("manual-execute")} className="secondary">手动执行</button><button onClick={() => respond("execute")}>执行</button><button onClick={() => respond("clear-and-execute")}>清除后执行</button></div></div>;
}

function transportLabel(status: string): string {
  return ({ idle: "未连接", loading: "加载历史", connected: "已连接", reconnecting: "重连中", error: "连接错误", closed: "已关闭" } as Record<string, string>)[status] ?? status;
}

function runtimeNoticeText(notice: { kind: "retry"; attempt: number; maxAttempts: number; delayMs: number; errorMessage: string } | { kind: "compaction"; reason: string }): string {
  return notice.kind === "retry" ? `正在重试 ${notice.attempt}/${notice.maxAttempts}（${Math.round(notice.delayMs / 1000)}s）· ${notice.errorMessage}` : `正在压缩上下文（${notice.reason}）`;
}
