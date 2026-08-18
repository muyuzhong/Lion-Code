"""Agent usage 的唯一账本与预算决策。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .core.messages import Usage

_MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """一次只读的 Agent usage 投影，不暴露账本的可变状态。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    turns: int = 0
    responses: int = 0
    last_prompt_tokens: int = 0
    last_response_at: float | None = None
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    """预算检查结果；Policy 不记录已超限状态。"""

    exceeded: bool
    kind: Literal["max_cost", "max_turns"] | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    """读取 UsageSnapshot 的无状态预算规则。"""

    max_cost_usd: float | None = None
    max_turns: int | None = None

    def check(self, usage: UsageSnapshot) -> BudgetDecision:
        """按 cost、turns 的既有优先级判断是否停止。"""

        if self.max_cost_usd is not None and usage.cost_usd >= self.max_cost_usd:
            return BudgetDecision(
                exceeded=True,
                kind="max_cost",
                reason=(
                    f"Cost limit reached (${usage.cost_usd:.4f} >= "
                    f"${self.max_cost_usd})"
                ),
            )
        if self.max_turns is not None and usage.turns >= self.max_turns:
            return BudgetDecision(
                exceeded=True,
                kind="max_turns",
                reason=(f"Turn limit reached ({usage.turns} >= {self.max_turns})"),
            )
        return BudgetDecision(exceeded=False)


class UsageLedger:
    """拥有一个 Agent 当前 Session 的全部可变 usage 状态。"""

    __slots__ = (
        "_cache_read_tokens",
        "_cache_write_tokens",
        "_input_tokens",
        "_last_prompt_tokens",
        "_last_response_at",
        "_output_tokens",
        "_responses",
        "_turns",
    )

    def __init__(self) -> None:
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._turns = 0
        self._responses = 0
        self._last_prompt_tokens = 0
        self._last_response_at: float | None = None

    def record_model_usage(
        self,
        usage: Usage,
        *,
        response_at: float | None = None,
    ) -> None:
        """累计一个助手终态响应并更新最近一次模型调用。"""

        self._input_tokens += usage.input
        self._output_tokens += usage.output
        self._cache_read_tokens += usage.cache_read
        self._cache_write_tokens += usage.cache_write
        self._responses += 1
        self._last_prompt_tokens = usage.total_tokens or (
            usage.input + usage.cache_read + usage.cache_write + usage.output
        )
        self._last_response_at = response_at

    def record_child_usage(self, input_tokens: int, output_tokens: int) -> None:
        """累计 child/Skill 返回量，不改变父响应、turn 或上下文跟踪。"""

        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def record_turn(self) -> None:
        """记录一个进入工具调用边界的 Core turn。"""

        self._turns += 1

    def reset(self) -> None:
        """清空当前 Session 的全部 usage。"""

        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._turns = 0
        self._responses = 0
        self._last_prompt_tokens = 0
        self._last_response_at = None

    def reset_context_tracking(self) -> None:
        """只清空上下文窗口 prompt 跟踪，保留累计 usage。"""

        self._last_prompt_tokens = 0

    def snapshot(self) -> UsageSnapshot:
        """返回不与账本内部状态共享可变引用的冻结快照。"""

        return UsageSnapshot(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cache_read_tokens=self._cache_read_tokens,
            cache_write_tokens=self._cache_write_tokens,
            turns=self._turns,
            responses=self._responses,
            last_prompt_tokens=self._last_prompt_tokens,
            last_response_at=self._last_response_at,
            cost_usd=(
                self._input_tokens * 3
                + self._cache_read_tokens * 0.3
                + self._cache_write_tokens * 3.75
                + self._output_tokens * 15
            )
            / _MILLION,
        )
