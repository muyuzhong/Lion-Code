"""Memory 条目的共享行渲染：recall 工具与 QueryContextLayer 使用同一形状。

行形状（设计 6.3）：``- [m:id scope/kind] stable_key: body Evidence: ...
[Paths: ...] [status]``——id 与 evidence 让模型能显式验证、更新或报告噪声。
"""

from __future__ import annotations

from .store import MemoryEntry


def entry_line(entry: MemoryEntry) -> str:
    """渲染单条 memory 行；behavior 带 trigger，definition 只带 content。"""
    if entry.kind == "behavior":
        # behavior 的 trigger 非空由 schema CHECK 保证
        body = f"When: {entry.trigger} Do: {entry.content}"
    else:
        body = entry.content
    suffix = f" Evidence: {'; '.join(entry.evidence)}"
    if entry.paths:
        suffix += f" Paths: {', '.join(entry.paths)}"
    if entry.status != "active":
        suffix += f" [{entry.status}]"
    return f"- [m:{entry.id} {entry.display_path()}] {entry.stable_key}: {body}{suffix}"
