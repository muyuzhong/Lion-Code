from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from nanoagent.ai import Model, StreamAccumulator, StreamOptions, stream
from nanoagent.agent.context import TransformContext, assemble_context
from nanoagent.agent.control import ControlSource
from nanoagent.agent.events import (
    AgentEnd,
    AgentEvent,
    AgentStart,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    TurnEnd,
    TurnStart,
)
from nanoagent.agent.messages import AgentMessage, ConvertToLlm, default_convert_to_llm
from nanoagent.agent.result import RunResult, StopReason
from nanoagent.agent.tools import AgentTool


@dataclass
class AgentLoopConfig:
    model: Model
    convert_to_llm: ConvertToLlm = default_convert_to_llm
    transform_context: TransformContext | None = None
    max_turns: int = 10
    control: ControlSource | None = None
    before_tool_call: Callable[..., Awaitable[dict | None]] | None = None
    get_steering_messages: Callable[[], Awaitable[list[AgentMessage]]] | None = None
    stream_fn: Callable[..., Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning: str | None = None


def _options(config: AgentLoopConfig, signal: Any) -> StreamOptions:
    return StreamOptions(
        signal=signal,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        reasoning=config.reasoning,
    )


async def agent_loop(
    *,
    prompts: list[AgentMessage],
    system_prompt: list[str],
    messages: list[AgentMessage],
    tools: list[AgentTool],
    config: AgentLoopConfig,
    signal: Any = None,
) -> AsyncIterator[AgentEvent]:
    history: list[AgentMessage] = [*messages, *prompts]
    produced: list[AgentMessage] = [*prompts]
    stream_fn = config.stream_fn or stream

    yield AgentStart()
    yield TurnStart()
    for p in prompts:
        yield MessageStart(message=p)
        yield MessageEnd(message=p)

    ctx = await assemble_context(
        system_prompt, history, tools, config.convert_to_llm, config.transform_context, signal
    )
    acc = StreamAccumulator(
        model_id=config.model.id, provider=config.model.provider, api=config.model.api
    )
    assistant = None
    async for event in stream_fn(config.model, ctx, _options(config, signal)):
        acc.add(event)
        if event.type == "start":
            yield MessageStart(message=acc.message)
        elif event.type in ("done", "error"):
            assistant = event.message
        else:
            yield MessageUpdate(message=acc.message, assistant_event=event)
    assert assistant is not None
    history.append(assistant)
    produced.append(assistant)
    yield MessageEnd(message=assistant)
    yield TurnEnd(message=assistant, tool_results=[])

    result = RunResult(reason=StopReason.COMPLETED, final_message_id=assistant.id)
    yield AgentEnd(messages=produced, result=result)
