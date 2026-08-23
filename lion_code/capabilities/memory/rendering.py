"""显式 Memory 工具共用的小型文本投影。"""

from __future__ import annotations

from dataclasses import dataclass

from ...context.estimator import estimate_text_tokens
from .store import (
    MAX_PINNED_ENTRIES,
    PINNED_MEMORY_TOKEN_BUDGET,
    MemoryEntry,
    TaskEntry,
)


def entry_line(entry: MemoryEntry) -> str:
    body = (
        f"When: {entry.trigger} Do: {entry.content}"
        if entry.kind == "behavior"
        else entry.content
    )
    paths = f" Paths: {', '.join(entry.paths)}" if entry.paths else ""
    return (
        f"- [m:{entry.id} {entry.display_path()}] {entry.stable_key}: {body} "
        f"Evidence: {entry.evidence_type}:{entry.evidence_ref}{paths}"
    )


def task_line(task: TaskEntry, *, detailed: bool) -> str:
    if not detailed:
        return (
            f"- [t:{task.id}] {task.stable_key}: {task.title}; next: {task.next_action}"
        )
    refs = f" Refs: {', '.join(task.refs)}" if task.refs else ""
    return (
        f"- [t:{task.id}] {task.stable_key}: {task.title}\n"
        f"  Objective: {task.objective}\n"
        f"  Summary: {task.summary}\n"
        f"  Next: {task.next_action}{refs}"
    )


@dataclass(frozen=True, slots=True)
class PinnedSelection:
    entries: tuple[MemoryEntry, ...]
    overflow: tuple[MemoryEntry, ...]


def select_pinned(entries: list[MemoryEntry]) -> PinnedSelection:
    """在固定上限内保留整条内容；超大条目不得阻塞后续小条目。"""
    kept: list[MemoryEntry] = []
    overflow: list[MemoryEntry] = []
    used = 0
    for entry in entries:
        cost = estimate_text_tokens(entry_line(entry))
        if len(kept) >= MAX_PINNED_ENTRIES or used + cost > PINNED_MEMORY_TOKEN_BUDGET:
            overflow.append(entry)
            continue
        kept.append(entry)
        used += cost
    return PinnedSelection(tuple(kept), tuple(overflow))
