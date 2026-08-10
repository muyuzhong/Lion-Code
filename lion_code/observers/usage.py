"""把助手终态事件转发到 Agent UsageLedger。"""

from __future__ import annotations

from time import time

from lion_code.core.events import AgentEvent, MessageEndEvent
from lion_code.core.messages import AssistantMessage
from lion_code.usage import UsageLedger


class UsageObserver:
    """无状态事件适配器；usage 累计状态只由 Ledger 拥有。"""

    def __init__(self, ledger: UsageLedger) -> None:
        self._ledger = ledger

    async def handle(self, event: AgentEvent) -> None:
        if not isinstance(event, MessageEndEvent):
            return
        if not isinstance(event.message, AssistantMessage):
            return
        self._ledger.record_model_usage(event.message.usage, response_at=time())
