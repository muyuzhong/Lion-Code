import { ComposerPrimitive, unstable_useComposerInput, unstable_useSlashCommandAdapter } from "@assistant-ui/react";
import { ArrowUp, BookOpen, CornerDownRight, Ellipsis, Settings2, Shield, Sparkles, Square, WandSparkles } from "lucide-react";
import type { SkillSummary } from "../backend";

export function ComposerChrome({ isStreaming, queuedText, queueCount, hasSteering, runtimeNotice, metrics, model, permissionMode, thinkingLevel, skills, onQueuedTextChange, onSteer, onFollowUp, onContinue, onCompact, onOpenSettings }: {
  isStreaming: boolean;
  queuedText: string;
  queueCount: number;
  hasSteering: boolean;
  runtimeNotice: string | null;
  metrics: { steps: number; llm: string; tools: string };
  model: string;
  permissionMode: string;
  thinkingLevel: string;
  skills: SkillSummary[];
  onQueuedTextChange: (value: string) => void;
  onSteer: () => void;
  onFollowUp: () => void;
  onContinue: () => void;
  onCompact: () => void;
  onOpenSettings: () => void;
}) {
  const composer = unstable_useComposerInput();
  const slash = unstable_useSlashCommandAdapter({
    commands: skills.map((skill) => ({
      id: skill.name,
      label: `/${skill.name}`,
      description: skill.description ?? "项目技能",
      execute: () => composer.setText(`/${skill.name} `),
    })),
    removeOnExecute: true,
  });
  return (
    <>
      {runtimeNotice ? <p className="runtime-notice" role="status">{runtimeNotice}</p> : null}
      {queueCount > 0 ? <p className="queue-count">已排队 {queueCount} 项 <span>{hasSteering ? "包含立即转向" : "将在当前任务后继续"}</span></p> : null}
      {isStreaming ? <div className="run-metrics" aria-label="当前运行统计"><span>已处理 {metrics.steps} 个步骤</span><span>LLM {metrics.llm}</span><span>工具 {metrics.tools}</span></div> : null}
      {isStreaming ? (
        <div className="queue-controls">
          <input aria-label="追加运行指令" value={queuedText} onChange={(event) => onQueuedTextChange(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); onFollowUp(); } }} placeholder="追加指令" />
          <button type="button" onClick={onSteer}><CornerDownRight aria-hidden="true" size={14} />立即转向</button>
          <button type="button" onClick={onFollowUp}><ArrowUp aria-hidden="true" size={14} />排队</button>
        </div>
      ) : null}
      <ComposerPrimitive.Unstable_TriggerPopoverRoot>
        <ComposerPrimitive.Unstable_TriggerPopover char="/" adapter={slash.adapter} className="composer-skill-menu" aria-label="技能列表">
          <ComposerPrimitive.Unstable_TriggerPopover.Action {...slash.action} />
          <ComposerPrimitive.Unstable_TriggerPopoverItems>
            {(items) => <><div className="composer-skill-heading"><Sparkles aria-hidden="true" size={14} /><span>Skills</span><small>{items.length}</small></div>{items.map((item, index) => <ComposerPrimitive.Unstable_TriggerPopoverItem key={item.id} item={item} index={index} className="composer-skill-item"><strong>{item.label}</strong><small>{item.description}</small></ComposerPrimitive.Unstable_TriggerPopoverItem>)}</>}
          </ComposerPrimitive.Unstable_TriggerPopoverItems>
        </ComposerPrimitive.Unstable_TriggerPopover>
        <ComposerPrimitive.Root className="composer-shell">
          <div className="composer-input-wrap"><ComposerPrimitive.Input className="composer-input" placeholder="输入 / 调用命令" aria-label="消息" /></div>
        <div className="composer-toolbar">
          <div className="composer-left">
            <span className="composer-mode"><Shield aria-hidden="true" size={15} />智能体</span>
            <span className="composer-mode">{permissionMode}</span>
            {!isStreaming ? <details className="composer-more"><summary className="composer-tool" aria-label="更多操作" title="更多操作"><Ellipsis aria-hidden="true" size={15} /></summary><div className="composer-more-menu"><button type="button" onClick={(event) => { onContinue(); event.currentTarget.closest("details")?.removeAttribute("open"); }}><BookOpen aria-hidden="true" size={14} /><span><strong>继续</strong><small>让智能体继续当前任务</small></span></button><button type="button" onClick={(event) => { onCompact(); event.currentTarget.closest("details")?.removeAttribute("open"); }}><WandSparkles aria-hidden="true" size={14} /><span><strong>压缩上下文</strong><small>释放当前会话上下文</small></span></button></div></details> : null}
          </div>
          <div className="composer-right">
            <button type="button" className="composer-model" aria-label="打开模型设置" onClick={onOpenSettings}><Settings2 aria-hidden="true" size={13} />{model}</button><button type="button" className="composer-thinking" aria-label="打开思考级别设置" onClick={onOpenSettings}>{thinkingLevel}</button>
            {isStreaming
              ? <ComposerPrimitive.Cancel className="stop-btn" aria-label="停止"><Square aria-hidden="true" size={12} /></ComposerPrimitive.Cancel>
              : <ComposerPrimitive.Send className="send-btn" aria-label="发送"><ArrowUp aria-hidden="true" size={16} /></ComposerPrimitive.Send>}
          </div>
        </div>
        </ComposerPrimitive.Root>
      </ComposerPrimitive.Unstable_TriggerPopoverRoot>
    </>
  );
}
