import { BookOpen, Check, ChevronDown, File, GitBranch, Globe2, PanelRightClose, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Streamdown } from "streamdown";
import { useLionRuntime } from "../assistantRuntime";
import type { GitReviewDiff, GitReviewFile, GitReviewSnapshot, OpenableResourceResponse, OpenableResourceStatus } from "../backend";

type WorkView = "工作面板" | "浏览器" | "文件" | "Git";

export function WorkPanel({ onClose, onResizeStart, onResizeBy }: { onClose: () => void; onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void; onResizeBy: (delta: number) => void }) {
  const { snapshot } = useLionRuntime();
  const [view, setView] = useState<WorkView>("工作面板");
  const openedResourcePath = snapshot.openedResource?.ref.path ?? null;
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
  useEffect(() => {
    if (openedResourcePath) setView("文件");
  }, [openedResourcePath]);
  const viewIcon = (option: WorkView) => option === "浏览器" ? <Globe2 aria-hidden="true" size={15} /> : option === "文件" ? <File aria-hidden="true" size={15} /> : option === "Git" ? <GitBranch aria-hidden="true" size={15} /> : <BookOpen aria-hidden="true" size={15} />;
  return (
    <aside className="work-panel" aria-label="工作面板">
      <div className="work-panel-resize" role="separator" aria-label="调整工作面板宽度" aria-orientation="vertical" tabIndex={0} onPointerDown={onResizeStart} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); onResizeBy(10); } if (event.key === "ArrowRight") { event.preventDefault(); onResizeBy(-10); } }} />
      <header className="work-panel-header">
        <details className="work-panel-context"><summary className="work-panel-switcher" aria-label="切换工作面板视图"><BookOpen aria-hidden="true" size={16} /><strong>{view}</strong><ChevronDown aria-hidden="true" size={14} /></summary><div className="work-panel-context-menu">{(["工作面板", "浏览器", "文件", "Git"] as WorkView[]).map((option) => <button key={option} type="button" className={option === view ? "active" : ""} onClick={(event) => selectView(option, event.currentTarget)}>{viewIcon(option)}<span>{option}</span>{option === view ? <Check aria-hidden="true" size={14} /> : null}</button>)}</div></details>
        <button type="button" className="work-panel-collapse" aria-label="关闭工作面板" onClick={onClose}><PanelRightClose aria-hidden="true" size={16} /></button>
      </header>
      <div className="work-panel-body">
        {view === "Git" ? <GitReviewTab /> : view === "文件" && snapshot.openedResource ? <FileResourceTab /> : <div className="work-tab-empty">
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

const RESOURCE_STATUS_LABELS: Record<OpenableResourceStatus, string> = {
  ready: "已加载",
  missing: "文件不存在",
  outside_workspace: "路径不在允许范围内",
  not_file: "不是普通文件",
  too_large: "文件过大",
  binary: "二进制文件",
  encoding_error: "编码不受支持",
  changed: "文件已变化",
  unreadable: "文件无法读取",
};

function FileResourceTab() {
  const { adapter, snapshot } = useLionRuntime();
  const opened = snapshot.openedResource;
  if (!opened) return null;
  const response = opened.response;
  const path = response?.path ?? opened.ref.path;
  const name = response?.name ?? resourceName(opened.ref.path);
  return (
    <div className="file-resource">
      <header className="file-resource-header">
        <div className="file-resource-title">
          <strong>{name}</strong>
          <span title={path}>{path}</span>
        </div>
        <button type="button" className="git-review-refresh" aria-label="重新加载文件" disabled={opened.loading} onClick={() => void adapter.reloadOpenedResource()}>
          <RefreshCw aria-hidden="true" size={14} />
        </button>
      </header>
      {response ? <div className="file-resource-meta"><span>{RESOURCE_STATUS_LABELS[response.status]} · {formatResourceSize(response.size)}</span><span>{formatResourceTime(response.modifiedAtNs)}</span></div> : null}
      <div className="file-resource-body">
        {opened.loading ? <div className="file-resource-state">正在读取文件…</div>
          : opened.error ? <div className="file-resource-state file-resource-error" role="alert">文件读取失败：{opened.error}</div>
            : response?.status !== "ready" ? <div className="file-resource-state file-resource-error" role="alert">{response ? RESOURCE_STATUS_LABELS[response.status] : "文件不可用"}：{response?.message ?? "未返回可显示内容"}</div>
              : <FileResourceContent response={response} />}
      </div>
    </div>
  );
}

function FileResourceContent({ response }: { response: OpenableResourceResponse }) {
  const content = response.content ?? "";
  if (response.format === "markdown") return <div className="file-resource-markdown"><Streamdown>{content}</Streamdown></div>;
  if (response.format === "diff") return <pre className="file-resource-diff">{renderDiffLines(content)}</pre>;
  return <pre className="file-resource-text">{content}</pre>;
}

function renderDiffLines(text: string) {
  return text.split("\n").map((line, index) => <span className={line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-remove" : line.startsWith("@@") ? "diff-hunk" : ""} key={index}>{line}{"\n"}</span>);
}

function resourceName(path: string): string {
  return path.split(/[\\/]/).at(-1) || "文件";
}

function formatResourceSize(size: number | null): string {
  if (size === null) return "大小未知";
  if (size < 1024) return `${size} B`;
  return `${(size / 1024).toFixed(1)} KiB`;
}

function formatResourceTime(modifiedAtNs: string | null): string {
  if (!modifiedAtNs) return "修改时间未知";
  const milliseconds = Number(modifiedAtNs) / 1_000_000;
  if (!Number.isFinite(milliseconds)) return "修改时间未知";
  return new Date(milliseconds).toLocaleString();
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
    return <div className="git-review"><div className="git-review-state git-review-error">Git 读取失败：{error}</div></div>;
  }
  if (!snapshot) {
    return <div className="git-review"><div className="git-review-state">暂无变更</div></div>;
  }
  if (snapshot.state === "non_git") {
    return <div className="git-review"><div className="git-review-state">当前工作区不是 Git 仓库</div></div>;
  }
  if (snapshot.state === "unborn") {
    return <div className="git-review"><div className="git-review-state">仓库还没有提交（unborn）</div></div>;
  }
  if (snapshot.state === "git_failed") {
    return <div className="git-review"><div className="git-review-state git-review-error">无法读取 Git 状态（命令失败）</div></div>;
  }
  if (snapshot.clean) {
    return <div className="git-review"><div className="git-review-state">工作区干净</div></div>;
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
