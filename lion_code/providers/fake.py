"""确定性回放的测试用 Provider。

按预置事件流逐次响应 `stream_response`,并记录每次调用的入参,
供应用层/TUI 测试在不接真实后端的情况下驱动完整 Agent 闭环。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

from lion_code.core.messages import AgentMessage
from lion_code.core.tools import AgentTool

from .events import AssistantMessageEvent
from .provider import CancellationToken


class FakeProvider:
    """A provider that replays predefined assistant event streams."""

    def __init__(self, streams: Iterable[Iterable[AssistantMessageEvent]]) -> None:
        self._streams = [list(stream) for stream in streams]
        self.calls: list[tuple[str, str, list[AgentMessage], list[AgentTool]]] = []

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        self.calls.append((model, system, list(messages), list(tools)))
        stream = self._streams.pop(0) if self._streams else []

        async def iterator() -> AsyncIterator[AssistantMessageEvent]:
            for event in stream:
                if signal is not None and signal.is_cancelled():
                    return
                yield event

        return iterator()
