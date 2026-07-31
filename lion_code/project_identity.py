"""按 Git worktree 或规范 cwd 标识项目。"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    """项目存储和项目上下文共用的稳定身份。"""

    root: Path
    key: str
    is_git: bool


def resolve_project_identity(cwd: Path | None = None) -> ProjectIdentity:
    """优先使用当前 worktree 根；非 Git 目录退回规范 cwd。"""

    resolved_cwd = (cwd or Path.cwd()).resolve()
    git_root = _git_root(resolved_cwd)
    root = git_root or resolved_cwd
    return ProjectIdentity(
        root=root,
        key=hashlib.sha256(_path_key(root).encode("utf-8")).hexdigest()[:16],
        is_git=git_root is not None,
    )


def project_storage_dir(identity: ProjectIdentity | None = None) -> Path:
    """返回项目级本地数据目录，不在此处创建具体子目录。"""

    current = identity or resolve_project_identity()
    return Path.home() / ".lion-code" / "projects" / current.key


def _git_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            encoding="utf-8",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    root = Path(result.stdout.strip()).resolve()
    try:
        cwd.relative_to(root)
    except ValueError:
        return None
    return root


def _path_key(path: Path) -> str:
    raw = os.path.realpath(os.fspath(path))
    if os.name == "nt" and raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return os.path.normcase(raw)
