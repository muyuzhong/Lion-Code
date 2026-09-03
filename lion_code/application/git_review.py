"""只读 Git 工作区审查快照（Desktop WorkPanel Git 视图的数据源）。

本模块与 ``GitStatusLayer``（ContextLayer，受每次渲染与 3 文件限制约束）
保持独立：它只按用户显式刷新提供相对 HEAD 的只读变更快照，不做任何写操作。
子进程约束复用已验证模式（workspace-local ``.git``、``stdin=DEVNULL``、
临时文件 stdout、可收敛 timeout），不捕获 PIPE 读线程。
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal

GIT_TIMEOUT = 2.0
MAX_FILES = 500
MAX_DIFF_BYTES = 64 * 1024

type GitReviewState = Literal["ok", "non_git", "unborn", "git_failed"]
type GitReviewFileStatus = Literal[
    "modified", "added", "deleted", "renamed", "untracked"
]

# porcelain 工作区/索引位（XY）映射到用户可见状态；unmerged 归为 modified。
_WORKTREE_STATUS: dict[str, GitReviewFileStatus] = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "renamed",
    "U": "modified",
    "T": "modified",
}


class GitReviewError(RuntimeError):
    """Git 读取失败；调用方不得把失败折叠为空快照。"""


@dataclass(frozen=True)
class GitReviewFile:
    path: str
    status: GitReviewFileStatus
    additions: int | None = None
    deletions: int | None = None
    binary: bool = False


@dataclass(frozen=True)
class GitReviewSnapshot:
    state: GitReviewState
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
    ``ok``。只有已确认成功的 Git 读取才会生成 ``ok`` 快照；任何命令非零
    返回、超时或启动失败都进入 ``git_failed``，不会伪装成 clean。
    """
    if not (cwd / ".git").exists():
        return _empty_snapshot("non_git")

    try:
        # 先确认 .git 是可用的当前仓库，再把 HEAD 不存在区分为 unborn。
        repo_code, _ = _run_git(cwd, "rev-parse", "--is-inside-work-tree")
        if repo_code != 0:
            raise GitReviewError("无法读取 Git 工作区")

        status_code, status_text = _run_git(
            cwd, "status", "--porcelain=v1", "--untracked-files=normal", "-z"
        )
        if status_code != 0:
            raise GitReviewError("无法读取 Git 状态")
        head_code, head_sha = _run_git(cwd, "rev-parse", "--verify", "HEAD")
        head_sha = head_sha.strip()
        branch_code, branch = _run_git(cwd, "branch", "--show-current")
        if branch_code != 0:
            raise GitReviewError("无法读取 Git 分支")
        if head_code != 0:
            # 状态读取已成功；此时 HEAD 不存在才是合法的 unborn 仓库。
            return _empty_snapshot(
                "unborn", branch=branch.strip() or "(detached)", revision=head_sha
            )
        numstat_code, numstat_text = _run_git(
            cwd, "diff", "--numstat", "-z", "-M", "HEAD"
        )
        if numstat_code != 0:
            raise GitReviewError("无法读取 Git 变更统计")
        parsed = _parse_status(status_text)
        stats = _parse_numstat(numstat_text)
        truncated = len(parsed) > MAX_FILES
        files = tuple(_build_file(file, stats) for file in parsed[:MAX_FILES])
        additions_total = sum(file.additions or 0 for file in files)
        deletions_total = sum(file.deletions or 0 for file in files)
        revision = _revision_digest(
            head_sha,
            status_text,
            numstat_text,
            parsed[:MAX_FILES],
            cwd,
            truncated=truncated,
        )
        return GitReviewSnapshot(
            state="ok",
            branch=branch.strip() or "(detached)",
            revision=revision,
            clean=not files,
            truncated=truncated,
            files=files,
            additions_total=additions_total,
            deletions_total=deletions_total,
        )
    except (GitReviewError, OSError):
        return _empty_snapshot("git_failed")


def read_git_file_diff(cwd: Path, raw_path: str) -> GitReviewFileDiff | None:
    """返回单个当前变更文件的有界 diff；越界路径返回 ``None``。

    仅接受当前变更集内的相对路径：绝对路径、``..`` 越界、resolve 后逃出
    workspace、或不在当前 status 中的路径都返回 ``None``，防止任意路径读取。
    Git 读取失败抛出 ``GitReviewError``，由 REST 层呈现为明确错误。二进制
    文件只报类型；untracked 返回空 diff；超过 ``MAX_DIFF_BYTES`` 截断。
    """
    path = _validate_path(cwd, raw_path)
    if path is None or not (cwd / ".git").exists():
        return None

    status_code, status_text = _run_git_for_diff(
        cwd, "status", "--porcelain=v1", "--untracked-files=normal", "-z"
    )
    if status_code != 0:
        raise GitReviewError("无法读取 Git 状态")
    changed = {file.path: file for file in _parse_status(status_text)}
    file = changed.get(path)
    if file is None:
        return None
    if file.status == "untracked":
        return GitReviewFileDiff(
            path=path, diff="", binary=False, truncated=False, untracked=True
        )

    numstat_code, numstat_text = _run_git_for_diff(
        cwd, "diff", "--numstat", "-z", "-M", "HEAD", "--", path
    )
    if numstat_code != 0:
        raise GitReviewError("无法读取 Git 变更统计")
    stats = _parse_numstat(numstat_text).get(path)
    binary = stats[2] if stats is not None else False
    if binary:
        return GitReviewFileDiff(
            path=path, diff="", binary=True, truncated=False, untracked=False
        )

    diff_code, diff_text = _run_git_for_diff(
        cwd,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "HEAD",
        "--",
        path,
    )
    if diff_code != 0:
        raise GitReviewError("无法读取 Git diff")
    truncated = len(diff_text.encode("utf-8")) > MAX_DIFF_BYTES
    if truncated:
        diff_text = _truncate_utf8(diff_text, MAX_DIFF_BYTES)
    return GitReviewFileDiff(
        path=path,
        diff=diff_text,
        binary=False,
        truncated=truncated,
        untracked=False,
    )


def _run_git(cwd: Path, *arguments: str) -> tuple[int, str]:
    """运行只读 Git 命令并返回 ``(returncode, stdout)``。

    只读取 workspace 自身仓库；启动失败、超时和非零返回由调用方判为
    ``git_failed``。使用临时文件 stdout 而非 PIPE，使 timeout 真正可收敛
    （sidecar 控制线程长期持有 stdin 的已知约束）。
    """
    try:
        with tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
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
    except (OSError, subprocess.SubprocessError):
        # timeout 等：返回非零码，由每个调用方进入明确失败路径。
        return 1, ""


def _run_git_for_diff(cwd: Path, *arguments: str) -> tuple[int, str]:
    """将 Git 启动异常转换为单文件 diff 的明确失败类型。"""
    try:
        return _run_git(cwd, *arguments)
    except OSError as exc:
        raise GitReviewError("无法读取 Git") from exc


def _empty_snapshot(
    state: GitReviewState,
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
    """解析 ``--porcelain=v1 -z``，保留特殊字符并正确处理 rename。

    machine-readable 输出中的 rename 记录按 ``新路径\\0旧路径`` 排列；只把
    新路径投影为当前文件，避免依赖 Git 为引号、换行进行的文本转义。
    """
    files: list[GitReviewFile] = []
    records = status_text.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        xy, path = record[:2], record[3:]
        if xy == "??":
            status: GitReviewFileStatus = "untracked"
        elif xy[0] in {"R", "C"} or xy[1] in {"R", "C"}:
            status = "renamed"
        else:
            status = _WORKTREE_STATUS.get(
                xy[1], _WORKTREE_STATUS.get(xy[0], "modified")
            )
        if xy[0] in {"R", "C"} or xy[1] in {"R", "C"}:
            # -z 已将新路径放在状态记录中，旧路径是下一个 NUL 字段。
            if index < len(records):
                index += 1
        files.append(GitReviewFile(path=path, status=status))
    return files


def _parse_numstat(
    numstat_text: str,
) -> dict[str, tuple[int | None, int | None, bool]]:
    """解析 ``git diff --numstat -z -M HEAD``，键为工作树路径。

    普通记录为 ``adds\\tdels\\tpath\\0``；rename 记录为
    ``adds\\tdels\\t\\0old\\0new\\0``，因此不能按换行或简单 tab 切分。
    """
    stats: dict[str, tuple[int | None, int | None, bool]] = {}
    records = numstat_text.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        parts = record.split("\t", 2)
        if len(parts) != 3:
            continue
        adds_raw, dels_raw, path = parts
        if adds_raw == "-" and dels_raw == "-":
            value: tuple[int | None, int | None, bool] = (None, None, True)
        elif adds_raw.isdigit() and dels_raw.isdigit():
            value = (int(adds_raw), int(dels_raw), False)
        else:
            continue
        if not path and index + 1 < len(records):
            # rename/copy 的旧路径、新路径紧随空 path 字段。
            index += 1
            path = records[index]
            index += 1
        stats[path] = value
    return stats


def _build_file(
    file: GitReviewFile,
    stats: dict[str, tuple[int | None, int | None, bool]],
) -> GitReviewFile:
    """用 numstat 补充增删与二进制标记；untracked 无 numstat。"""
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


def _revision_digest(
    head_sha: str,
    status_text: str,
    numstat_text: str,
    files: list[GitReviewFile],
    cwd: Path,
    *,
    truncated: bool,
) -> str:
    """生成能区分工作区内容的有界版本摘要。

    Git 的 raw diff 对未暂存内容可能只给出全零的新 blob，不能单独用于
    revision。这里只对当前展示范围内的文件读取有限内容，避免为刷新快照
    额外生成整棵工作区的完整 diff。
    """
    digest = hashlib.sha256()
    for value in (head_sha, status_text, numstat_text, str(truncated)):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    for file in files:
        digest.update(file.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.status.encode("ascii"))
        digest.update(b"\0")
        target = cwd / file.path
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        except OSError as exc:
            raise GitReviewError("无法读取工作区版本") from exc

        digest.update(
            f"{info.st_mode}:{info.st_size}:{info.st_mtime_ns}".encode("ascii")
        )
        digest.update(b"\0")
        try:
            if stat.S_ISLNK(info.st_mode):
                digest.update(os.readlink(target).encode("utf-8", errors="replace"))
            elif stat.S_ISREG(info.st_mode):
                _hash_bounded_file(digest, target, info.st_size)
        except OSError as exc:
            raise GitReviewError("无法读取工作区版本") from exc
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _hash_bounded_file(digest: hashlib._Hash, path: Path, size: int) -> None:
    """把文件首尾内容加入摘要，单文件读取量不超过 ``MAX_DIFF_BYTES``。"""
    with path.open("rb") as source:
        if size <= MAX_DIFF_BYTES:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
            return
        half = MAX_DIFF_BYTES // 2
        digest.update(source.read(half))
        source.seek(-half, os.SEEK_END)
        digest.update(source.read(half))


def _validate_path(cwd: Path, raw: str) -> str | None:
    """校验路径是相对路径且 resolve 后仍在 workspace 内。"""
    candidate = Path(raw)
    if (
        not raw
        or candidate.is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or ntpath.isabs(raw)
        or ".." in candidate.parts
        or ".." in PureWindowsPath(raw).parts
    ):
        return None
    try:
        if not (cwd / raw).resolve().is_relative_to(cwd.resolve()):
            return None
    except (OSError, ValueError):
        return None
    return raw


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """按字节截断且保持 UTF-8 字符边界完整。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    cut = encoded[:max_bytes]
    while cut and cut[-1] & 0xC0 == 0x80:
        cut = cut[:-1]
    return cut.decode("utf-8", errors="replace")
