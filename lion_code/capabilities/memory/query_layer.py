"""Memory 自动召回的 QueryContextLayer：prepared-only 的纯读投影。

设计 6 节契约：

- pinned（active + recall_mode=pinned，long_term + 当前 project）每次
  Provider request 都渲染，400-token 预算内按 project 优先、kind、
  stable_key 稳定截断（溢出由 ``review_memory`` 报警）；
- relevant 按 latest user query 复用 ``MemoryStore.search`` 流水线
  （top 6、800-token 预算），全部 path 失效的条目不注入（设计 7.2）；
- 两集合都为空时返回空字符串，不注入噪声块；
- 渲染只做本地同步 SQLite 读取，不调用 Provider、不写库、不写 Session。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ...context.estimator import estimate_text_tokens
from ...context.types import ContextView
from .rendering import entry_line
from .store import (
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_TOP_K,
    PINNED_TOKEN_BUDGET,
    MemoryEntry,
    MemoryStore,
)

# 末尾权威性说明（设计 6.3 原文）：memory 是历史上下文，当前指令优先
AUTHORITY_NOTE = (
    "Memory is historical context. Current user instructions, AGENTS, "
    "source and tests win."
)
# 设计 6.3 的分区标题：pinned 先于 relevant，relevant 内 definitions 先于 behaviors
_PINNED_SECTIONS = (
    ("Pinned Behaviors", "behavior"),
    ("Pinned Definitions", "definition"),
)
_RELEVANT_SECTIONS = (
    ("Relevant Definitions", "definition"),
    ("Relevant Behaviors", "behavior"),
)
# pinned 截断优先级：project 条目优先保留，behavior 先于 definition，
# 其余按 stable_key 排序保证同输入下截断结果确定
_PINNED_SCOPE_ORDER = {"project": 0, "long_term": 1}
_PINNED_KIND_ORDER = {"behavior": 0, "definition": 1}


def _budgeted(entries: Sequence[MemoryEntry], budget: int) -> list[MemoryEntry]:
    """按顺序保留预算内的条目；首条超预算同样截断。

    硬预算（设计 6.2：pinned 400 / relevant 800 / 合计 ≤1200）不允许
    单条超限例外；全部超限时集合为空，由 ``render`` 走空结果不注入路径。
    """
    used = 0
    kept: list[MemoryEntry] = []
    for entry in entries:
        cost = estimate_text_tokens(entry_line(entry))
        if used + cost > budget:
            break
        used += cost
        kept.append(entry)
    return kept


def _render_section(
    sections: tuple[tuple[str, str], ...],
    entries: Sequence[MemoryEntry],
) -> str:
    lines: list[str] = []
    for heading, kind in sections:
        group = [entry for entry in entries if entry.kind == kind]
        if not group:
            continue
        lines.append(f"## {heading}")
        lines.extend(entry_line(entry) for entry in group)
    return "\n".join(lines)


class MemoryQueryContextLayer:
    """把 pinned/relevant memory 渲染为 ``# Active Memory`` 投影块。"""

    layer_id = "memory"

    def __init__(self, store: MemoryStore, *, project_root: Path | None) -> None:
        self._store = store
        self._project_root = project_root

    def render(self, query: str, view: ContextView) -> str:
        # view 属于 SPI 契约（未来可读 utilization 调整预算），当前渲染
        # 不依赖它；显式舍弃以表明没有隐藏的 per-request 状态。
        del view
        pinned = self._pinned_entries()
        relevant = self._relevant_entries(query)
        if not pinned and not relevant:
            return ""
        sections = [
            rendered
            for rendered in (
                _render_section(_PINNED_SECTIONS, pinned),
                _render_section(_RELEVANT_SECTIONS, relevant),
            )
            if rendered
        ]
        return "\n\n".join(("# Active Memory", *sections, AUTHORITY_NOTE))

    # ------------------------------------------------------------------
    # pinned：每次渲染，稳定截断
    # ------------------------------------------------------------------

    def _pinned_entries(self) -> list[MemoryEntry]:
        entries = self._store.pinned()
        entries.sort(
            key=lambda entry: (
                _PINNED_SCOPE_ORDER[entry.scope],
                _PINNED_KIND_ORDER[entry.kind],
                entry.stable_key,
            )
        )
        return _budgeted(entries, PINNED_TOKEN_BUDGET)

    # ------------------------------------------------------------------
    # relevant：latest query 驱动，复用 PR3 检索流水线
    # ------------------------------------------------------------------

    def _relevant_entries(self, query: str) -> list[MemoryEntry]:
        hits = self._store.search(query, top_k=DEFAULT_TOP_K)
        entries = [hit.entry for hit in hits]
        # 全部 path 失效的条目剔除为 stale candidate（只读，不改库）
        entries, _candidates = MemoryStore.partition_by_path_health(
            entries, self._project_root
        )
        return _budgeted(entries, DEFAULT_TOKEN_BUDGET)
