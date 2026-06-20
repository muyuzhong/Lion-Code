import pytest
from pydantic import BaseModel

from nanoagent.ai import TextContent, UserMessage
from nanoagent.ai import stream as ai_stream
from nanoagent.ai.provider import clear_providers
from nanoagent.ai.providers.mock import create_mock_model, register_mock
from nanoagent.agent.control import AbortSignal
from nanoagent.agent.loop import AgentLoopConfig, agent_loop
from nanoagent.agent.result import StopReason
from nanoagent.agent.tools import AgentTool, AgentToolResult


class _Args(BaseModel):
    pass


class _Tool(AgentTool):
    name = "t"
    description = "d"
    parameters = _Args
    label = "T"

    async def execute(self, tool_call_id, params, signal=None):
        return AgentToolResult(content=[TextContent(text="ran")])


async def _run(cfg, tools=None):
    return [
        e
        async for e in agent_loop(
            prompts=[UserMessage(content="go")],
            system_prompt=[],
            messages=[],
            tools=tools or [],
            config=cfg,
        )
    ]


@pytest.mark.asyncio
async def test_transform_context_error_maps_to_run_error():
    clear_providers()
    register_mock()
    mock = create_mock_model(responses=[{"content": ["hi"]}])

    async def boom(messages, signal):
        raise RuntimeError("transform boom")

    events = await _run(AgentLoopConfig(model=mock, transform_context=boom))
    end = events[-1]
    assert end.type == "agent_end"
    assert end.result.reason is StopReason.ERROR
    assert "transform boom" in (end.result.error or "")


@pytest.mark.asyncio
async def test_convert_to_llm_error_maps_to_run_error():
    clear_providers()
    register_mock()
    mock = create_mock_model(responses=[{"content": ["hi"]}])

    def boom(messages):
        raise RuntimeError("convert boom")

    events = await _run(AgentLoopConfig(model=mock, convert_to_llm=boom))
    assert events[-1].result.reason is StopReason.ERROR
    assert "convert boom" in (events[-1].result.error or "")


@pytest.mark.asyncio
async def test_stream_fn_error_maps_to_run_error():
    clear_providers()
    register_mock()
    mock = create_mock_model()

    def boom(model, ctx, options):
        raise RuntimeError("stream boom")

    events = await _run(AgentLoopConfig(model=mock, stream_fn=boom))
    assert events[-1].result.reason is StopReason.ERROR
    assert "stream boom" in (events[-1].result.error or "")


@pytest.mark.asyncio
async def test_request_approval_error_maps_to_run_error():
    clear_providers()
    register_mock()
    mock = create_mock_model(
        responses=[{"content": [{"type": "toolCall", "name": "t", "arguments": {}}]}]
    )

    class BoomControl:
        async def request_approval(self, tool_call, tier):
            raise RuntimeError("approval boom")

    events = await _run(AgentLoopConfig(model=mock, control=BoomControl()), tools=[_Tool()])
    assert events[-1].result.reason is StopReason.ERROR
    assert "approval boom" in (events[-1].result.error or "")


@pytest.mark.asyncio
async def test_before_tool_call_error_maps_to_run_error():
    clear_providers()
    register_mock()
    mock = create_mock_model(
        responses=[{"content": [{"type": "toolCall", "name": "t", "arguments": {}}]}]
    )

    async def boom(call, params):
        raise RuntimeError("before boom")

    events = await _run(AgentLoopConfig(model=mock, before_tool_call=boom), tools=[_Tool()])
    assert events[-1].result.reason is StopReason.ERROR
    assert "before boom" in (events[-1].result.error or "")


@pytest.mark.asyncio
async def test_abort_during_streaming_skips_tools_and_aborts_run():
    """A provider that ignores options.signal must not get its tool calls run.

    Reproduces the P1: abort() lands mid-stream (after the turn's top-of-loop
    abort check) and the provider streams to completion with a normal TOOL_USE
    stop reason. The loop must re-check the signal after streaming and terminate
    ABORTED instead of executing the assistant's tool calls.
    """
    clear_providers()
    register_mock()
    mock = create_mock_model(
        responses=[{"content": [{"type": "toolCall", "name": "t", "arguments": {}}]}]
    )

    ran = {"n": 0}

    class _CountingTool(AgentTool):
        name = "t"
        description = "d"
        parameters = _Args
        label = "T"

        async def execute(self, tool_call_id, params, signal=None):
            ran["n"] += 1
            return AgentToolResult(content=[TextContent(text="ran")])

    signal = AbortSignal()

    async def aborting_stream(model, ctx, options):
        # Cancellation lands mid-stream; the provider does not cooperatively stop.
        async for event in ai_stream(model, ctx, options):
            if event.type == "start":
                options.signal.abort()
            yield event

    events = [
        e
        async for e in agent_loop(
            prompts=[UserMessage(content="go")],
            system_prompt=[],
            messages=[],
            tools=[_CountingTool()],
            config=AgentLoopConfig(model=mock, stream_fn=aborting_stream),
            signal=signal,
        )
    ]

    assert ran["n"] == 0, "tools must not run after an abort during streaming"
    assert not any(e.type == "tool_execution_start" for e in events)
    end = events[-1]
    assert end.type == "agent_end"
    assert end.result.reason is StopReason.ABORTED
