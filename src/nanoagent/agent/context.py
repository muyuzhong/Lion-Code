from __future__ import annotations

from typing import Any, Awaitable, Callable

from nanoagent.ai import Context
from nanoagent.agent.messages import AgentMessage, ConvertToLlm
from nanoagent.agent.tools import AgentTool

TransformContext = Callable[[list[AgentMessage], Any], Awaitable[list[AgentMessage]]]


async def assemble_context(
    system_prompt: list[str],
    messages: list[AgentMessage],
    tools: list[AgentTool],
    convert_to_llm: ConvertToLlm,
    transform_context: TransformContext | None = None,
    signal: Any = None,
) -> Context:
    """装配 provider 可消费的 wire Context。

    transform_context 是上下文压缩、裁剪或注入的机制入口；默认不做策略判断。
    """

    # 只复制列表结构，不深拷贝消息对象；hook 可以重排/替换列表，但不污染调用方持有的列表。
    msgs = list(messages)
    if transform_context is not None:
        msgs = await transform_context(msgs, signal)
    wire = convert_to_llm(msgs)
    return Context(
        system_prompt=list(system_prompt),
        messages=wire,
        tools=[t.to_wire() for t in tools],
    )
