"""供应商无关 Context 投影阈值。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """从旧供应商专用路径迁移出的稳定策略值。"""

    budget_start_ratio: float = 0.50
    aggressive_budget_ratio: float = 0.70
    snip_start_ratio: float = 0.60
    hot_cache_override_ratio: float = 0.75
    auto_compact_ratio: float = 0.85
    normal_result_budget_chars: int = 30_000
    aggressive_result_budget_chars: int = 15_000
    keep_recent_results: int = 3
    cache_idle_seconds: float = 5 * 60
    snip_placeholder: str = "[Content snipped - re-read if needed]"
    cleared_placeholder: str = "[Old result cleared]"
