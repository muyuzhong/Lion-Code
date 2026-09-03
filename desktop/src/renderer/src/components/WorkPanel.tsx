import { BookOpen, Check, ChevronDown, File, GitBranch, Globe2, PanelRightClose, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useLionRuntime } from "../assistantRuntime";
import type { GitReviewDiff, GitReviewFile, GitReviewSnapshot } from "../backend";

type WorkView = "工作面板" | "浏览器" | "文件" | "Git";

export function WorkPanel({ onClose, onResizeStart, onResizeBy }: { onClose: () => void; onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void; onResizeBy: (delta: number) => void }) {
  const [view, setView] = useState<WorkView>("工作面板");
  const emptyCopy = view === "浏览器"
    ? { title: "还没有打开的浏览器", body: "从对话中的链接打开页面，浏览内容会显示在这里。" }
    : view === "文件"
      ? { title: "还没有打开的文件", body: "从对话中的文件路径打开资源，内容会显示在这里。" }
      : view === "Git"
        ? { title: "还没有查看的变更", body: "打开 Git 视图查看当前工作区相对 HEAD 的变更。" }
        : { title: "还没有打开的资源", body: "从对话里的文件、命令或链接打开，也可以直接选择下面的工具。" };
  const selectView = (nextView: WorkView, target: HTMLElement) => {
    setView(nextView);
    target.closest("details")?.removeAttribute("open");
  };
  const viewIcon = (option: WorkView) => option === "浏览器" ? <Globe2 aria-hidden="true" size={15} /> : option === "文件" ? <File aria-hidden="true" size={15} /> : option === "Git" ? <GitBranch aria-hidden="true" size={15} /> : <BookOpen aria-hidden="true" size={15} />;
  return (
    <aside className="work-panel" aria-label="工作面板">
      <div className="work-panel-resize" role="separator" aria-label="调整工作面板宽度" aria-orientation="vertical" tabIndex={0} onPointerDown={onResizeStart} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); onResizeBy(10); } if (event.key === "ArrowRight") { event.preventDefault(); onResizeBy(-10); } }} />
      <header className="work-panel-header">
        <details className="work-panel-context"><summary className="work-panel-switcher" aria-label="切换工作面板视图"><BookOpen aria-hidden="true" size={16} /><strong>{view}</strong><ChevronDown aria-hidden="true" size={14} /></summary><div className="work-panel-context-menu">{(["工作面板", "浏览器", "文件", "Git"] as WorkView[]).map((option) => <button key={option} type="button" className={option === view ? "active" : ""} onClick={(event) => selectView(option, event.currentTarget)}>{viewIcon(option)}<span>{option}</span>{option === view ? <Check aria-hidden="true" size={14} /> : null}</button>)}</div></details>
        <button type="button" className="work-panel-collapse" aria-label="关闭工作面板" onClick={onClose}><PanelRightClose aria-hidden="true" size={16} /></button>
      </header>
      <div className="work-panel-body">
        {view === "Git" ? <GitReviewTab /> : <div className="work-tab-empty">
          <span className="work-tab-empty-icon"><BookOpen aria-hidden="true" size={20} /></span>
          <h2>{emptyCopy.title}</h2>
          <p>{emptyCopy.body}</p>
          <div className="work-panel-empty-tools">
            <button type="button" className={view === "浏览器" ? "active" : ""} onClick={() => setView("浏览器")}><Globe2 aria-hidden="true" size={16} />浏览器</button>
            <button type="button" className={view === "文件" ? "active" : ""} onClick={() => setView("文件")}><File aria-hidden="true" size={16} />文件</button>
          </div>
        </div>}
      </div>
    </aside>
  );
}

type GitStatus = "modified" | "added" | "deleted" | "renamed" | "untracked";

const STATUS_LABELS: Record<GitStatus, string> = {
  modified: "M",
  added: "A",
  deleted: "D",
  renamed: "R",
  untracked: "U",
};

function GitReviewTab() {
  const { adapter } = useLionRuntime();
  const [snapshot, setSnapshot] = useState<GitReviewSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [diffs, setDiffs] = useState<Record<string, GitReviewDiff>>({});
  const [diffErrors, setDiffErrors] = useState<Record<string, string>>({});
  const [diffLoading, setDiffLoading] = useState<Record<string, boolean>>({});
  const requestRef = useRef(0);

  const refresh = useCallback(() => {
    const request = ++requestRef.current;
    setLoading(true);
    setError(null);
    setExpanded(null);
    setDiffs({});
    setDiffErrors({});
    setDiffLoading({});
    void adapter.fetchGitReview().then((result) => {
      if (request !== requestRef.current) return; // 丢弃陈旧返回
      setLoading(false);
      if (result === null) {
        setError("无法读取 Git 状态");
        return;
      }
      setSnapshot(result);
    }).catch(() => {
      if (request !== requestRef.current) return;
      setLoading(false);
      setError("无法读取 Git 状态");
    });
  }, [adapter]);

  useEffect(() => { refresh(); }, [refresh]);

  const renderState = (message: string, isError = false) => (
    <div className="git-review">
      <div className={`git-review-state${isError ? " git-review-error" : ""}`}>
        <span>{message}</span>
        <button type="button" className="git-review-refresh" aria-label="刷新 Git 状态" onClick={refresh}>
          <RefreshCw aria-hidden="true" size={14} />
        </button>
      </div>
    </div>
  );

  const loadDiff = useCallback((file: GitReviewFile) => {
    if (expanded === file.path) {
      setExpanded(null);
      return;
    }
    setExpanded(file.path);
    if (file.binary || file.status === "untracked") return;
    if (diffs[file.path]) return;
    const snapshotRequest = requestRef.current;
    setDiffErrors((current) => {
      const next = { ...current };
      delete next[file.path];
      return next;
    });
    setDiffLoading((current) => ({ ...current, [file.path]: true }));
    void adapter.fetchGitReviewDiff(file.path).then((result) => {
      if (snapshotRequest !== requestRef.current) return;
      setDiffLoading((current) => ({ ...current, [file.path]: false }));
      if (result) {
        setDiffs((current) => ({ ...current, [file.path]: result }));
        return;
      }
      setDiffErrors((current) => ({ ...current, [file.path]: "无法读取该文件 diff" }));
    }).catch(() => {
      if (snapshotRequest !== requestRef.current) return;
      setDiffLoading((current) => ({ ...current, [file.path]: false }));
      setDiffErrors((current) => ({ ...current, [file.path]: "无法读取该文件 diff" }));
    });
  }, [adapter, expanded, diffs]);

  if (loading) {
    return <div className="git-review"><div className="git-review-state">正在读取 Git 状态…</div></div>;
  }
  if (error) {
    return renderState(`Git 读取失败：${error}`, true);
  }
  if (!snapshot) {
    return renderState("暂无变更");
  }
  if (snapshot.state === "non_git") {
    return renderState("当前工作区不是 Git 仓库");
  }
  if (snapshot.state === "unborn") {
    return renderState("仓库还没有提交（unborn）");
  }
  if (snapshot.state === "git_failed") {
    return renderState("无法读取 Git 状态（命令失败）", true);
  }
  if (snapshot.clean) {
    return renderState("工作区干净");
  }
  const diff = expanded ? diffs[expanded] : undefined;
  const expandedDiffError = expanded ? diffErrors[expanded] : undefined;
  const expandedDiffLoading = expanded ? diffLoading[expanded] === true : false;
  return (
    <div className="git-review">
      <div className="git-review-header">
        <span className="git-review-branch">{snapshot.branch}</span>
        <span className="git-review-counts">+{snapshot.additions_total} / -{snapshot.deletions_total} · {snapshot.files.length} 个文件</span>
        <button type="button" className="git-review-refresh" aria-label="刷新 Git 状态" onClick={refresh}><RefreshCw aria-hidden="true" size={14} /></button>
      </div>
      {snapshot.truncated ? <div className="git-review-truncated">变更较多，仅显示前 {snapshot.files.length} 个文件</div> : null}
      <ul className="git-review-files">
        {snapshot.files.map((file) => (
          <li key={file.path} className="git-review-file">
            <button type="button" className={expanded === file.path ? "active" : ""} onClick={() => loadDiff(file)}>
              <span className={`git-review-status ${file.status}`}>{STATUS_LABELS[file.status]}</span>
              <span className="git-review-path">{file.path}</span>
              {file.binary ? <span className="git-review-binary">二进制</span>
                : file.additions === null || file.deletions === null
                  ? <span className="git-review-stats">—</span>
                  : <span className="git-review-stats">+{file.additions}/-{file.deletions}</span>}
            </button>
            {expanded === file.path ? <GitReviewDiffView diff={diff} error={expandedDiffError} loading={expandedDiffLoading} file={file} /> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function GitReviewDiffView({ diff, error, loading, file }: { diff: GitReviewDiff | undefined; error: string | undefined; loading: boolean; file: GitReviewFile }) {
  if (file.binary || (diff && diff.binary)) {
    return <div className="git-review-diff"><pre className="git-review-diff-note">二进制文件，不显示文本 diff</pre></div>;
  }
  if (file.status === "untracked") {
    return <div className="git-review-diff"><pre className="git-review-diff-note">未跟踪文件，无 diff</pre></div>;
  }
  if (error) {
    return <div className="git-review-diff"><pre className="git-review-diff-note git-review-error">Git diff 读取失败：{error}</pre></div>;
  }
  if (loading || !diff) {
    return <div className="git-review-diff"><pre className="git-review-diff-note">正在加载 diff…</pre></div>;
  }
  const text = diff.diff;
  if (!text) {
    return <div className="git-review-diff"><pre className="git-review-diff-note">没有可显示的文本 diff</pre></div>;
  }
  return (
    <div className="git-review-diff">
      <pre className="diff-result">{text.split("\n").map((line, index) => <span className={line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-remove" : line.startsWith("@@") ? "diff-hunk" : ""} key={index}>{line}{"\n"}</span>)}</pre>
      {diff?.truncated ? <div className="git-review-truncated">diff 过长，已截断</div> : null}
    </div>
  );
}
