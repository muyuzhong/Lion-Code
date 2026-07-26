"""Usage 累计观察器：聚合每条助手消息的 token 用量与费用。

不硬编码模型价格：Provider 未提供 cost 时保持 0，后续由独立的
``PricingPolicy`` 注入，避免把价格规则塞回 Agent。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time

from lion_code.core.events import AgentEvent, MessageEndEvent
from lion_code.core.messages import AssistantMessage, Usage


@dataclass(slots=True)
class UsageTotals:
    """跨多次助手响应累计的用量与费用。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0


class UsageObserver:
    """订阅 Agent 事件并累计助手消息 usage 的异步观察器。"""

    def __init__(self) -> None:
        self._totals = UsageTotals()
        self._last_usage: Usage | None = None
        self._last_response_at: float | None = None

    @property
    def totals(self) -> UsageTotals:
        """返回当前累计的快照（修改快照不影响观察器内部状态）。"""
        return UsageTotals(
            input_tokens=self._totals.input_tokens,
            output_tokens=self._totals.output_tokens,
            cache_read_tokens=self._totals.cache_read_tokens,
            cache_write_tokens=self._totals.cache_write_tokens,
            reasoning_tokens=self._totals.reasoning_tokens,
            cost_usd=self._totals.cost_usd,
        )

    @property
    def last_usage(self) -> Usage | None:
        """返回最近一次助手响应的独立 Usage 快照。"""

        if self._last_usage is None:
            return None
        return self._last_usage.model_copy(deep=True)

    @property
    def last_response_at(self) -> float | None:
        """返回最近一次带 Usage 的助手终态事件时间。"""

        return self._last_response_at

    async def handle(self, event: AgentEvent) -> None:
        if not isinstance(event, MessageEndEvent):
            return
        if not isinstance(event.message, AssistantMessage):
            return

        usage = event.message.usage
        self._last_usage = usage.model_copy(deep=True)
        self._last_response_at = time()
        self._totals.input_tokens += usage.input
        self._totals.output_tokens += usage.output
        self._totals.cache_read_tokens += usage.cache_read
        self._totals.cache_write_tokens += usage.cache_write
        self._totals.reasoning_tokens += usage.reasoning or 0
        self._totals.cost_usd += usage.cost.total
