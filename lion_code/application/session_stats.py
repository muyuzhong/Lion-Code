"""会话累计统计视图类型(vendored 自 tau_coding/session_stats.py 的子集)。

数值来源是 Lion 的 UsageObserver 与应用层计数,不复刻 Tau 基于
Session Entry 重放的计算;LionCodingSession 在阶段 3 负责填充。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionStats:
    """Cumulative activity and billed usage for one active branch."""

    turn_count: int = 0
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None
