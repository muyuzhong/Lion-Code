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
    """Assemble the wire Context. transform_context = compaction/pruning seam (no-op stub by default)."""
    msgs = messages
    if transform_context is not None:
        msgs = await transform_context(messages, signal)
    wire = convert_to_llm(msgs)
    return Context(
        system_prompt=list(system_prompt),
        messages=wire,
        tools=[t.to_wire() for t in tools],
    )
