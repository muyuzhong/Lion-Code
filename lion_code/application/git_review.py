"""只读 Git 工作区审查快照（Desktop WorkPanel Git 视图的数据源）。

本模块与 ``GitStatusLayer``（ContextLayer，受每次渲染与 3 文件限制约束）
保持独立：它只按用户显式刷新提供相对 HEAD 的只读变更快照，不做任何写操作。
子进程约束复用已验证模式（workspace-local ``.git``、``stdin=DEVNULL``、
临时文件 stdout、可收敛 timeout），不捕获 PIPE 读线程。
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT = 2.0
MAX_FILES = 500
MAX_DIFF_BYTES = 64 * 1024

# porcelain 工作区/索引位（XY）映射到用户可见状态；unmerged 归为 modified。
_WORKTREE_STATUS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "U": "modified",
}


@dataclass(frozen=True)
class GitReviewFile:
    path: str
    status: str
    additions: int | None = None
    deletions: int | None = None
    binary: bool = False


@dataclass(frozen=True)
class GitReviewSnapshot:
    state: str
    branch: str
    revision: str
    clean: bool
    truncated: bool
    files: tuple[GitReviewFile, ...]
    additions_total: int
    deletions_total: int


@dataclass(frozen=True)
class GitReviewFileDiff:
    path: str
    diff: str
    binary: bool
    truncated: bool
    untracked: bool = False


def read_git_review(cwd: Path) -> GitReviewSnapshot:
    """返回 workspace 相对 HEAD 的只读变更快照。

    ``state`` 取值 ``non_git`` / ``unborn``（无提交）/ ``git_failed`` /
    ``ok``。``git_failed`` 与 ``clean`` 严格分离：Git 命令失败不会伪装成
    空列表。文件数超 ``MAX_FILES`` 时只保留前 N 条并置 ``truncated``。
    """
    if not (cwd / ".git").exists():
        return _empty_snapshot("non_git")
    try:
        head_code, head_sha = _run_git(cwd, "rev-parse", "--verify", "HEAD")
        head_sha = head_sha.strip()
        branch = _run_git(cwd, "branch", "--show-current")[1].strip() or "(detached)"
        if head_code != 0:
            # 仓库存在但没有提交：HEAD 尚不存在。
            return _empty_snapshot("unborn", branch=branch, revision=head_sha)
        status_text = _run_git(cwd, "status", "--porcelain", "--untracked-files=normal")[1]
        numstat_text = _run_git(cwd, "diff", "--numstat", "HEAD", "-M")[1]
    except OSError:
        # git 二进制缺失等；与「无变更」严格分离。
        return _empty_snapshot("git_failed")

    parsed = _parse_status(status_text)
    stats = _parse_numstat(numstat_text)
    truncated = len(parsed) > MAX_FILES
    files = tuple(_build_file(file, stats) for file in parsed[:MAX_FILES])
    additions_total = sum(file.additions or 0 for file in files)
    deletions_total = sum(file.deletions or 0 for file in files)
    revision = _revision_digest(head_sha, status_text)
    return GitReviewSnapshot(
        state="ok",
        branch=branch,
        revision=revision,
        clean=not files,
        truncated=truncated,
        files=files,
        additions_total=additions_total,
        deletions_total=deletions_total,
    )


def read_git_file_diff(cwd: Path, raw_path: str) -> GitReviewFileDiff | None:
    """返回单个当前变更文件的有界 diff；越界路径返回 ``None``。

    仅接受当前变更集内的相对路径：绝对路径、``..`` 越界、resolve 后逃出
    workspace、或不在当前 status 中的路径都返回 ``None``，防止任意路径读取。
    二进制文件只报类型；untracked 返回空 diff；超过 ``MAX_DIFF_BYTES``
    截断并置 ``truncated``。
    """
    try:
        path = _safe_changed_path(cwd, raw_path)
        if path is None:
            return None
        _, status = _run_git(cwd, "status", "--porcelain", "--untracked-files=normal", "--", path)
        untracked = any(line.startswith("??") for line in status.splitlines())
        _, numstat = _run_git(cwd, "diff", "--numstat", "HEAD", "-M", "--", path)
        binary = _is_binary(numstat)
        diff_text = ""
        if not untracked and not binary:
            _, diff_text = _run_git(cwd, "diff", "--no-color", "--no-ext-diff", "HEAD", "--", path)
        truncated = len(diff_text.encode("utf-8")) > MAX_DIFF_BYTES
        if truncated:
            diff_text = _truncate_utf8(diff_text, MAX_DIFF_BYTES)
        return GitReviewFileDiff(
            path=path,
            diff=diff_text,
            binary=binary,
            truncated=truncated,
            untracked=untracked,
        )
    except OSError:
        return None


def _run_git(cwd: Path, *arguments: str) -> tuple[int, str]:
    """运行只读 Git 命令并返回 ``(returncode, stdout)``。

    只读取 workspace 自身仓库；``OSError``（git 二进制缺失等）向上传播，
    由调用方判为 ``git_failed``。使用临时文件 stdout 而非 PIPE，使 timeout
    真正可收敛（sidecar 控制线程长期持有 stdin 的已知约束）。
    """
    try:
        with tempfile.TemporaryFile(
            mode="w+",
            encoding="utf-8",
            errors="replace",
        ) as output:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GIT_TIMEOUT,
            )
            output.seek(0)
            return completed.returncode, output.read()
    except subprocess.SubprocessError:
        # timeout 等：视为命令失败，但与 OSError 区分开。
        return 1, ""


def _empty_snapshot(
    state: str,
    *,
    branch: str = "",
    revision: str = "",
) -> GitReviewSnapshot:
    return GitReviewSnapshot(
        state=state,
        branch=branch,
        revision=revision,
        clean=False,
        truncated=False,
        files=(),
        additions_total=0,
        deletions_total=0,
    )


def _parse_status(status_text: str) -> list[GitReviewFile]:
    """解析 ``--porcelain --untracked-files=normal`` 输出。

    rename/copy 取 `` -> `` 之后的新路径；untracked 目录被折叠为
    ``?? dir/`` 单条，天然避免 untracked 爆量。
    """
    files: list[GitReviewFile] = []
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        xy, path = line[:2], line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        if xy == "??":
            status = "untracked"
        else:
            status = _WORKTREE_STATUS.get(xy[1], _WORKTREE_STATUS.get(xy[0], "modified"))
        files.append(GitReviewFile(path=path, status=status))
    return files


def _parse_numstat(numstat_text: str) -> dict[str, tuple[int | None, int | None, bool]]:
    """解析 ``git diff --numstat -M HEAD``，键为路径。

    二进制行形如 ``-\t-\tpath`` → ``(None, None, True)``；其余为
    ``(adds, dels, False)``。
    """
    stats: dict[str, tuple[int | None, int | None, bool]] = {}
    for line in numstat_text.splitlines():
        adds_raw, dels_raw, path = line.partition("\t")[0], "", ""
        # 逐段拆分：path 本身可能含 tab
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds_raw, dels_raw = parts[0], parts[1]
        path = "\t".join(parts[2:])
        if adds_raw == "-" and dels_raw == "-":
            stats[path] = (None, None, True)
        elif adds_raw.isdigit() and dels_raw.isdigit():
            stats[path] = (int(adds_raw), int(dels_raw), False)
    return stats


def _build_file(file: GitReviewFile, stats: dict[str, tuple[int | None, int | None, bool]]) -> GitReviewFile:
    """用 numstat 补充增删与二进制标记；untracked 无 numstat 保持 ``None``。"""
    if file.path not in stats:
        return file
    adds, dels, binary = stats[file.path]
    return GitReviewFile(
        path=file.path,
        status=file.status,
        additions=None if binary else adds,
        deletions=None if binary else dels,
        binary=binary,
    )


def _revision_digest(head_sha: str, status_text: str) -> str:
    """HEAD sha 与 status 输出共同决定 revision，工作区内容变化即可辨识。"""
    import hashlib

    return hashlib.sha256(f"{head_sha}\x00{status_text}".encode("utf-8")).hexdigest()[:16]


def _is_binary(numstat_text: str) -> bool:
    return any(line.split("\t")[:2] == ["-", "-"] for line in numstat_text.splitlines() if line)


def _safe_changed_path(cwd: Path, raw: str) -> str | None:
    """校验路径属于当前变更集且不会逃出 workspace。"""
    if not raw or Path(raw).is_absolute():
        return None
    if ".." in Path(raw).parts:
        return None
    try:
        if not (cwd / raw).resolve().is_relative_to(cwd.resolve()):
            return None
    except (OSError, ValueError):
        return None
    _, status = _run_git(cwd, "status", "--porcelain", "--untracked-files=normal")
    changed = {file.path for file in _parse_status(status)}
    return raw if raw in changed else None


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """按字节截断且保持 UTF-8 字符边界完整。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    cut = encoded[:max_bytes]
    while cut and cut[-1] & 0xC0 == 0x80:
        cut = cut[:-1]
    return cut.decode("utf-8", errors="replace")
