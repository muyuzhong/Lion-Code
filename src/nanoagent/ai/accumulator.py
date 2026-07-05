from __future__ import annotations

from typing import AsyncIterator

from nanoagent.ai.events import AssistantMessageEvent
from nanoagent.ai.messages import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
)


class StreamAccumulator:
    """把 provider 的增量事件折叠成一个 AssistantMessage。

    这是 consumer/UI 友好的视图：同一条 assistant 消息在 start/update/end 之间保持稳定 id。
    """

    def __init__(self, model_id: str, provider: str, api: str):
        self._msg = AssistantMessage.empty(model_id, provider, api)

    @property
    def message(self) -> AssistantMessage:
        return self._msg

    def add(self, event: AssistantMessageEvent) -> None:
        """吸收一个流式事件，并更新当前累积消息。"""

        t = event.type
        if t == "text_start":
            self._msg.content.append(TextContent(text=""))
        elif t == "text_delta":
            block = self._msg.content[event.content_index]
            if isinstance(block, TextContent):
                block.text += event.delta
        elif t == "text_end":
            self._msg.content[event.content_index] = TextContent(text=event.text)
        elif t == "thinking_start":
            self._msg.content.append(ThinkingContent(thinking=""))
        elif t == "thinking_delta":
            block = self._msg.content[event.content_index]
            if isinstance(block, ThinkingContent):
                block.thinking += event.delta
        elif t == "thinking_end":
            self._msg.content[event.content_index] = ThinkingContent(thinking=event.thinking)
        elif t == "toolcall_start":
            # tool call 的完整参数通常到 end 才能解析；先放占位块保持 content_index 稳定。
            self._msg.content.append(ToolCall(id="", name="", arguments={}))
        elif t == "toolcall_end":
            self._msg.content[event.content_index] = event.tool_call
        elif t in ("done", "error"):
            # 采用 provider 给出的最终消息内容，但保留流式过程中的 id，
            # 让消费者在 message_start -> message_update -> message_end 之间看到同一身份。
            event.message.id = self._msg.id
            self._msg = event.message


async def accumulate(events: AsyncIterator[AssistantMessageEvent]) -> AssistantMessage:
    acc: StreamAccumulator | None = None
    async for event in events:
        if acc is None:
            acc = StreamAccumulator(model_id="", provider="", api="")
        acc.add(event)
    if acc is None:
        raise ValueError("stream produced no events")
    return acc.message
