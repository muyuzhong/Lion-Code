import { FileCheck2, ShieldAlert } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function ConfirmationSurface({ request, approve }: { request: string; approve: (approved: boolean) => void }) {
  const safeAction = useRef<HTMLButtonElement>(null);
  useEffect(() => safeAction.current?.focus(), []);
  return (
    <ApprovalFrame icon={<ShieldAlert size={18} />} kicker="需要确认" title="允许这项操作？" titleId="confirm-title" onCancel={() => approve(false)}>
      <p>{request}</p>
      <div className="approval-actions"><button ref={safeAction} onClick={() => approve(false)} className="button-quiet">保持阻止</button><button onClick={() => approve(true)}>允许一次</button></div>
    </ApprovalFrame>
  );
}

export function PlanApprovalSurface({ plan, respond }: { plan: string; respond: (choice: "clear-and-execute" | "execute" | "manual-execute" | "keep-planning") => void }) {
  const safeAction = useRef<HTMLButtonElement>(null);
  useEffect(() => safeAction.current?.focus(), []);
  return (
    <ApprovalFrame icon={<FileCheck2 size={18} />} kicker="执行计划" title="选择下一步" titleId="plan-title" className="plan-approval" onCancel={() => respond("keep-planning")}>
      <pre>{plan}</pre>
      <div className="approval-actions"><button ref={safeAction} onClick={() => respond("keep-planning")} className="button-quiet">继续规划</button><button onClick={() => respond("manual-execute")} className="button-quiet">我来执行</button><button onClick={() => respond("execute")}>按计划执行</button><button onClick={() => respond("clear-and-execute")}>清空上下文后执行</button></div>
    </ApprovalFrame>
  );
}

function ApprovalFrame({ icon, kicker, title, titleId, className = "", onCancel, children }: { icon: ReactNode; kicker: string; title: string; titleId: string; className?: string; onCancel: () => void; children: ReactNode }) {
  return <dialog className={`approval ${className}`} open aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); onCancel(); }}><header><span className="approval-icon" aria-hidden="true">{icon}</span><div><span className="workspace-kicker">{kicker}</span><h2 id={titleId}>{title}</h2></div></header>{children}</dialog>;
}
