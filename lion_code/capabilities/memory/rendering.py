"""显式 Memory 工具共用的小型文本投影。"""

from __future__ import annotations

from collections.abc import Sequence
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


def render_pinned(entries: Sequence[MemoryEntry]) -> str:
    """渲染完整 pinned 投影；空集合不产生上下文块。"""
    if not entries:
        return ""
    return (
        "# Pinned Memory\n"
        + "\n".join(entry_line(entry) for entry in entries)
        + "\n\nMemory is historical context; current user instructions, AGENTS, "
        "source, and tests take priority."
    )


@dataclass(frozen=True, slots=True)
class PinnedSelection:
    entries: tuple[MemoryEntry, ...]
    overflow: tuple[MemoryEntry, ...]


def select_pinned(entries: list[MemoryEntry]) -> PinnedSelection:
    """在固定上限内保留整条内容；超大条目不得阻塞后续小条目。"""
    kept: list[MemoryEntry] = []
    overflow: list[MemoryEntry] = []
    for entry in entries:
        candidate = (*kept, entry)
        if (
            len(kept) >= MAX_PINNED_ENTRIES
            or estimate_text_tokens(render_pinned(candidate))
            > PINNED_MEMORY_TOKEN_BUDGET
        ):
            overflow.append(entry)
            continue
        kept.append(entry)
    return PinnedSelection(tuple(kept), tuple(overflow))
