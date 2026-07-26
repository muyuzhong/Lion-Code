"""一次性无工具补全:消费 Provider 流并返回最终文本。

供 side-query 场景(Memory 召回、评估器、Auto Mode 分类器)复用,
替代直连 SDK 的旧实现。输出上限与采样由 Provider 配置决定,
不支持逐调用覆盖(协议层没有该参数)。
"""

from __future__ import annotations

from lion_code.core.messages import AgentMessage
from lion_code.core.provider import ModelProvider
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent


async def complete_text(
    provider: ModelProvider,
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
) -> str:
    """执行一次无工具补全,返回助手最终文本;流错误抛 RuntimeError。"""
    async for event in provider.stream_response(
        model=model,
        system=system,
        messages=messages,
        tools=[],
    ):
        if isinstance(event, AssistantDoneEvent):
            return event.message.text or ""
        if isinstance(event, AssistantErrorEvent):
            raise RuntimeError(
                event.error.error_message or f"side query failed: {event.reason}"
            )
    return ""
