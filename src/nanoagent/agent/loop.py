from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from nanoagent.ai import Model, StreamAccumulator, StreamOptions, TextContent, ToolResultMessage, stream
from nanoagent.ai import StopReason as WireStopReason
from nanoagent.agent.context import TransformContext, assemble_context
from nanoagent.agent.control import ControlSource
from nanoagent.agent.events import (
    AgentEnd,
    AgentEvent,
    AgentStart,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from nanoagent.agent.messages import AgentMessage, ConvertToLlm, default_convert_to_llm
from nanoagent.agent.result import RunResult, StopReason
from nanoagent.agent.tools import AgentTool, execute_tool_calls


@dataclass
class AgentLoopConfig:
    """agent_loop 的可注入配置。

    这里保持框架机制层：模型、消息转换、上下文变换、控制源和流式函数都由调用方注入，
    loop 本身不选择 provider、API key、权限策略或 token 预算。
    """

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


def _finish(
    produced: list[AgentMessage],
    reason: StopReason,
    final_message_id: str | None,
    error: str | None = None,
) -> AgentEnd:
    """构造唯一的终止事件：每次 run 都以一个 AgentEnd + RunResult 收尾。"""
    return AgentEnd(
        messages=produced,
        result=RunResult(reason=reason, final_message_id=final_message_id, error=error),
    )


async def _stream_one_turn(model, ctx, stream_fn, options):
    """把 provider 的细粒度流事件折叠成 agent 层的 message 生命周期片段。"""

    acc = StreamAccumulator(model_id=model.id, provider=model.provider, api=model.api)
    assistant = None
    async for event in stream_fn(model, ctx, options):
        acc.add(event)
        if event.type == "start":
            yield ("message_start", acc.message)
        elif event.type in ("done", "error"):
            assistant = event.message
        else:
            yield ("message_update", acc.message, event)
    yield ("__assistant__", assistant)


async def agent_loop(
    *,
    prompts: list[AgentMessage],
    system_prompt: list[str],
    messages: list[AgentMessage],
    tools: list[AgentTool],
    config: AgentLoopConfig,
    signal: Any = None,
) -> AsyncIterator[AgentEvent]:
    """执行一次 agent run，并按严格生命周期顺序产出事件。

    该函数只负责运行时机制：上下文装配、模型流式调用、工具调用和终止归因。
    具体工具权限、上下文裁剪、provider 选择等策略通过 config 中的 hook 注入。
    """

    history: list[AgentMessage] = [*messages, *prompts]
    produced: list[AgentMessage] = [*prompts]
    stream_fn = config.stream_fn or stream
    open_message: AgentMessage | None = None
    open_turn = False
    turn_message: AgentMessage | None = None
    open_tools: dict[str, ToolExecutionStart] = {}

    yield AgentStart()
    # prompt 是本次 run 新增的用户输入，也要进入事件流，便于 AgentState 和订阅者同步。
    for p in prompts:
        yield MessageStart(message=p)
        yield MessageEnd(message=p)

    try:
        async for event in _run_turns(
            history=history,
            produced=produced,
            system_prompt=system_prompt,
            tools=tools,
            config=config,
            stream_fn=stream_fn,
            signal=signal,
        ):
            if isinstance(event, TurnStart):
                open_turn = True
                turn_message = None
            elif isinstance(event, MessageStart):
                open_message = event.message
                if event.generated:
                    turn_message = event.message
            elif isinstance(event, MessageEnd):
                if open_message is not None and open_message.id == event.message.id:
                    open_message = None
                if getattr(event.message, "role", None) == "assistant":
                    turn_message = event.message
            elif isinstance(event, ToolExecutionStart):
                open_tools[event.tool_call_id] = event
            elif isinstance(event, ToolExecutionEnd):
                open_tools.pop(event.tool_call_id, None)
            elif isinstance(event, TurnEnd):
                open_turn = False
                turn_message = None
            yield event
    except Exception as exc:
        # 异常发生时先补齐已打开的生命周期，再产出 AgentEnd。
        # 这样 AgentState 不会残留 streaming_message 或 pending_tool_calls。
        if open_message is not None:
            if all(message.id != open_message.id for message in produced):
                history.append(open_message)
                produced.append(open_message)
            if getattr(open_message, "role", None) == "assistant":
                turn_message = open_message
            yield MessageEnd(message=open_message)
        for started in open_tools.values():
            result = ToolResultMessage(
                tool_call_id=started.tool_call_id,
                tool_name=started.tool_name,
                content=[TextContent(text=str(exc))],
                is_error=True,
                error=str(exc),
            )
            yield ToolExecutionEnd(
                tool_call_id=started.tool_call_id,
                tool_name=started.tool_name,
                result=result,
                is_error=True,
            )
        if open_turn:
            yield TurnEnd(message=turn_message, tool_results=[])
        last_id = produced[-1].id if produced else None
        yield _finish(produced, StopReason.ERROR, last_id, error=str(exc))


async def _run_turns(
    *,
    history: list[AgentMessage],
    produced: list[AgentMessage],
    system_prompt: list[str],
    tools: list[AgentTool],
    config: AgentLoopConfig,
    stream_fn: Any,
    signal: Any,
) -> AsyncIterator[AgentEvent]:
    """按回合推进模型和工具，直到完成、取消、错误或达到最大回合数。"""

    turn = 0
    while True:
        if signal is not None and signal.aborted:
            last_id = produced[-1].id if produced else None
            yield AgentEnd(
                messages=produced,
                result=RunResult(reason=StopReason.ABORTED, final_message_id=last_id),
            )
            return
        if turn >= config.max_turns:
            last_id = produced[-1].id if produced else None
            yield AgentEnd(
                messages=produced,
                result=RunResult(reason=StopReason.MAX_TURNS, final_message_id=last_id),
            )
            return
        turn += 1
        yield TurnStart()

        # steering 消息只在回合边界注入，保证本回合上下文一致；
        # 更复杂的 follow-up 队列应继续作为 hook/上层 harness 策略扩展。
        if config.get_steering_messages is not None:
            for steered in await config.get_steering_messages():
                history.append(steered)
                produced.append(steered)
                yield MessageStart(message=steered)
                yield MessageEnd(message=steered)

        ctx = await assemble_context(
            system_prompt, history, tools, config.convert_to_llm, config.transform_context, signal
        )
        assistant = None
        async for item in _stream_one_turn(config.model, ctx, stream_fn, _options(config, signal)):
            if item[0] == "message_start":
                yield MessageStart(message=item[1], generated=True)
            elif item[0] == "message_update":
                yield MessageUpdate(message=item[1], assistant_event=item[2])
            else:
                assistant = item[1]
        assert assistant is not None
        history.append(assistant)
        produced.append(assistant)
        yield MessageEnd(message=assistant)

        # 流式结束后再次检查取消信号：某些 provider 可能没有协作式停止。
        # 在工具执行前兑现取消，避免已取消的 run 继续调用工具或开启下一回合。
        if signal is not None and signal.aborted:
            yield TurnEnd(message=assistant, tool_results=[])
            yield AgentEnd(
                messages=produced,
                result=RunResult(reason=StopReason.ABORTED, final_message_id=assistant.id),
            )
            return

        if assistant.stop_reason in (WireStopReason.ERROR, WireStopReason.ABORTED):
            yield TurnEnd(message=assistant, tool_results=[])
            reason = (
                StopReason.ABORTED
                if assistant.stop_reason == WireStopReason.ABORTED
                else StopReason.ERROR
            )
            yield AgentEnd(
                messages=produced,
                result=RunResult(
                    reason=reason, final_message_id=assistant.id, error=assistant.error_message
                ),
            )
            return

        tool_calls = [c for c in assistant.content if getattr(c, "type", None) == "toolCall"]
        runnable = assistant.stop_reason in (WireStopReason.TOOL_USE, WireStopReason.STOP)
        if not (runnable and tool_calls):
            yield TurnEnd(message=assistant, tool_results=[])
            yield AgentEnd(
                messages=produced,
                result=RunResult(reason=StopReason.COMPLETED, final_message_id=assistant.id),
            )
            return

        # 先发出所有 start，再进行审批/执行；消费者可据此建立完整的工具批次视图。
        for c in tool_calls:
            yield ToolExecutionStart(tool_call_id=c.id, tool_name=c.name, args=c.arguments)

        approved: list = []
        denied_results: dict[str, ToolResultMessage] = {}
        for c in tool_calls:
            ok = True
            if config.control is not None:
                ok = await config.control.request_approval(c, "exec")
            if ok:
                approved.append(c)
            else:
                denied_results[c.id] = ToolResultMessage(
                    tool_call_id=c.id,
                    tool_name=c.name,
                    content=[TextContent(text="Tool approval denied")],
                    is_error=True,
                )

        executed = await execute_tool_calls(
            approved, tools, signal=signal, before_tool_call=config.before_tool_call
        )
        executed_by_id = {r.tool_call_id: r for r in executed}
        tool_results = [denied_results.get(c.id) or executed_by_id[c.id] for c in tool_calls]
        for c, r in zip(tool_calls, tool_results):
            yield ToolExecutionEnd(
                tool_call_id=c.id, tool_name=c.name, result=r, is_error=r.is_error
            )
        for r in tool_results:
            # 工具结果最终作为 transcript message 进入历史，下一回合模型才能看到。
            yield MessageStart(message=r)
            history.append(r)
            produced.append(r)
            yield MessageEnd(message=r)
        yield TurnEnd(message=assistant, tool_results=tool_results)
