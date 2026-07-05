from __future__ import annotations

import asyncio
from typing import Any, Protocol

from nanoagent.ai import ToolCall


class AbortSignal:
    """协作式取消信号。

    只暴露 provider 需要的 `.aborted` duck type；取消策略和触发时机由上层决定。
    """

    def __init__(self):
        self._event = asyncio.Event()
        self.reason: Any = None

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    def abort(self, reason: Any = None) -> None:
        if self.aborted:
            return
        self.reason = reason
        self._event.set()

    async def wait(self) -> Any:
        await self._event.wait()
        return self.reason


class ControlSource(Protocol):
    """工具执行前的控制入口，框架只询问结果，不内置审批策略。"""

    async def request_approval(self, tool_call: ToolCall, tier: str) -> bool: ...


class AllowAll:
    """框架默认实现：不设审批门槛，具体权限策略属于 harness。"""

    async def request_approval(self, tool_call: ToolCall, tier: str) -> bool:
        return True
