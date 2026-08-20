"""每次渲染都重新读取 Git 工作区状态的无状态 Capability。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...context.types import ContextView
from ..types import CapabilitySpec

_DIRTY_FILE_LIMIT = 3


class GitStatusLayer:
    """每次渲染实时读取 cwd、分支和 dirty files。"""

    layer_id = "git-status"

    def render(self, view: ContextView) -> str:
        del view
        cwd = Path.cwd()
        branch = _git_output(cwd, "branch", "--show-current") or "(detached)"
        status = _git_output(cwd, "status", "--porcelain", "--untracked-files=all")
        paths = _status_paths(status)

        lines = [
            f"Working directory: {cwd}",
            f"Branch: {branch}",
            f"Dirty files: {len(paths)}",
        ]
        lines.extend(f"- {path}" for path in paths[:_DIRTY_FILE_LIMIT])
        if len(paths) > _DIRTY_FILE_LIMIT:
            lines.append(f"- ... {len(paths) - _DIRTY_FILE_LIMIT} more")
        if not paths:
            lines.append("- clean")
        return "\n".join(lines)


def create_git_status_capability() -> CapabilitySpec:
    """返回无状态的 Git 工作区 ContextLayer。"""
    return CapabilitySpec(
        name="git-status",
        context_layer=GitStatusLayer(),
    )


def _git_output(cwd: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _status_paths(status: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for line in status.splitlines():
        if len(line) > 3:
            path = line[3:]
        else:
            path = line.strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        if path:
            paths.add(path)
    return tuple(sorted(paths))
