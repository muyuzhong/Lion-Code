import { BookOpen, Check, ChevronDown, File, Globe2, PanelRightClose } from "lucide-react";
import { useState, type PointerEvent as ReactPointerEvent } from "react";

type WorkView = "工作面板" | "浏览器" | "文件";

export function WorkPanel({ onClose, onResizeStart, onResizeBy }: { onClose: () => void; onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void; onResizeBy: (delta: number) => void }) {
  const [view, setView] = useState<WorkView>("工作面板");
  const emptyCopy = view === "浏览器"
    ? { title: "还没有打开的浏览器", body: "从对话中的链接打开页面，浏览内容会显示在这里。" }
    : view === "文件"
      ? { title: "还没有打开的文件", body: "从对话中的文件路径打开资源，内容会显示在这里。" }
      : { title: "还没有打开的资源", body: "从对话里的文件、命令或链接打开，也可以直接选择下面的工具。" };
  const selectView = (nextView: WorkView, target: HTMLElement) => {
    setView(nextView);
    target.closest("details")?.removeAttribute("open");
  };
  return (
    <aside className="work-panel" aria-label="工作面板">
      <div className="work-panel-resize" role="separator" aria-label="调整工作面板宽度" aria-orientation="vertical" tabIndex={0} onPointerDown={onResizeStart} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); onResizeBy(10); } if (event.key === "ArrowRight") { event.preventDefault(); onResizeBy(-10); } }} />
      <header className="work-panel-header">
        <details className="work-panel-context"><summary className="work-panel-switcher" aria-label="切换工作面板视图"><BookOpen aria-hidden="true" size={16} /><strong>{view}</strong><ChevronDown aria-hidden="true" size={14} /></summary><div className="work-panel-context-menu">{(["工作面板", "浏览器", "文件"] as WorkView[]).map((option) => <button key={option} type="button" className={option === view ? "active" : ""} onClick={(event) => selectView(option, event.currentTarget)}>{option === "浏览器" ? <Globe2 aria-hidden="true" size={15} /> : option === "文件" ? <File aria-hidden="true" size={15} /> : <BookOpen aria-hidden="true" size={15} />}<span>{option}</span>{option === view ? <Check aria-hidden="true" size={14} /> : null}</button>)}</div></details>
        <button type="button" className="work-panel-collapse" aria-label="关闭工作面板" onClick={onClose}><PanelRightClose aria-hidden="true" size={16} /></button>
      </header>
      <div className="work-panel-body">
        <div className="work-tab-empty">
          <span className="work-tab-empty-icon"><BookOpen aria-hidden="true" size={20} /></span>
          <h2>{emptyCopy.title}</h2>
          <p>{emptyCopy.body}</p>
          <div className="work-panel-empty-tools">
            <button type="button" className={view === "浏览器" ? "active" : ""} onClick={() => setView("浏览器")}><Globe2 aria-hidden="true" size={16} />浏览器</button>
            <button type="button" className={view === "文件" ? "active" : ""} onClick={() => setView("文件")}><File aria-hidden="true" size={16} />文件</button>
          </div>
        </div>
      </div>
    </aside>
  );
}
