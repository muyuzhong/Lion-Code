"""剧本驱动的 MockProvider。

它是离线单元测试和端到端集成测试的核心道具：每次 ``stream`` 调用严格消费
一条剧本，既能回放事件序列，也能在指定轮次稳定复现 Provider 异常。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator, List, Union

from providers.base import (
    MessageEnd,
    MessageStart,
    ModelProvider,
    ModelRequest,
    StreamEvent,
    TextDelta,
    ToolInputDelta,
    ToolUseEnd,
    ToolUseStart,
)
from runtime.blocks import Usage

ScriptEntry = Union[List[StreamEvent], Exception]


class MockProvider(ModelProvider):
    """按轮次回放事件；异常条目会在对应轮次直接抛出。"""

    def __init__(self, script: List[ScriptEntry]):
        self.script = list(script)
        self.requests: List[ModelRequest] = []
        self._index = 0

    @staticmethod
    def text_turn(text: str, usage: Usage = None) -> List[StreamEvent]:
        return [
            MessageStart(model="mock-model"),
            TextDelta(text=text),
            MessageEnd(stop_reason="end_turn", usage=usage or Usage(10, 5)),
        ]

    @staticmethod
    def tool_turn(
        name: str,
        tool_input: dict,
        tool_id: str = None,
        usage: Usage = None,
    ) -> List[StreamEvent]:
        tool_use_id = tool_id or f"tooluse_{uuid.uuid4().hex[:8]}"
        return [
            MessageStart(model="mock-model"),
            ToolUseStart(id=tool_use_id, name=name),
            ToolInputDelta(
                id=tool_use_id,
                partial_json=json.dumps(tool_input, ensure_ascii=False),
            ),
            ToolUseEnd(id=tool_use_id),
            MessageEnd(stop_reason="tool_use", usage=usage or Usage(10, 5)),
        ]

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if self._index >= len(self.script):
            # 剧本耗尽通常说明引擎意外多调用了一轮模型，必须让测试立刻暴露。
            raise AssertionError("MockProvider 剧本已耗尽")
        entry = self.script[self._index]
        self._index += 1
        if isinstance(entry, Exception):
            raise entry
        for event in entry:
            # 主动让出事件循环，使控制指令与取消逻辑可以在测试中真实调度。
            await asyncio.sleep(0)
            yield event
