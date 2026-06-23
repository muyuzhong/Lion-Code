import pytest
from pydantic import BaseModel

from nanoagent.ai import TextContent, UserMessage
from nanoagent.ai.provider import clear_providers
from nanoagent.ai.providers.mock import create_mock_model, register_mock
from nanoagent.agent.loop import AgentLoopConfig, agent_loop
from nanoagent.agent.result import StopReason
from nanoagent.agent.tools import AgentTool, AgentToolResult


class EchoArgs(BaseModel):
    text: str


class EchoTool(AgentTool):
    name = "echo"
    description = "echo"
    parameters = EchoArgs
    label = "Echo"

    async def execute(self, tool_call_id, params, signal=None):
        return AgentToolResult(content=[TextContent(text=f"echo:{params.text}")])


@pytest.mark.asyncio
async def test_tool_call_then_continue_completes():
    clear_providers()
    register_mock()
    mock = create_mock_model(
        responses=[
            {"content": [{"type": "toolCall", "name": "echo", "arguments": {"text": "yo"}}]},
            {"content": ["done"]},
        ]
    )
    cfg = AgentLoopConfig(model=mock)
    events = [
        e
        async for e in agent_loop(
            prompts=[UserMessage(content="go")],
            system_prompt=[],
            messages=[],
            tools=[EchoTool()],
            config=cfg,
        )
    ]
    types = [e.type for e in events]
    assert "tool_execution_start" in types and "tool_execution_end" in types
    end = events[-1]
    assert end.result.reason is StopReason.COMPLETED
    roles = [m.role for m in end.messages]
    assert roles == ["user", "assistant", "toolResult", "assistant"]
    assert end.messages[2].content[0].text == "echo:yo"
    assert mock.calls and len(mock.calls) == 2


@pytest.mark.asyncio
async def test_tool_execution_start_args_are_event_snapshot():
    clear_providers()
    register_mock()
    mock = create_mock_model(
        responses=[
            {"content": [{"type": "toolCall", "name": "echo", "arguments": {"text": "yo"}}]},
            {"content": ["done"]},
        ]
    )
    cfg = AgentLoopConfig(model=mock)
    events = []

    async for event in agent_loop(
        prompts=[UserMessage(content="go")],
        system_prompt=[],
        messages=[],
        tools=[EchoTool()],
        config=cfg,
    ):
        events.append(event)
        if event.type == "tool_execution_start":
            event.args["text"] = "mutated"

    end = events[-1]
    assert end.messages[2].content[0].text == "echo:yo"
