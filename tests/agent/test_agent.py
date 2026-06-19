import pytest
from pydantic import BaseModel

from nanoagent.ai import TextContent, UserMessage
from nanoagent.ai.provider import clear_providers
from nanoagent.ai.providers.mock import create_mock_model, register_mock
from nanoagent.agent.agent import Agent
from nanoagent.agent.result import StopReason
from nanoagent.agent.tools import AgentTool, AgentToolResult


class _NoopArgs(BaseModel):
    pass


class _NoopTool(AgentTool):
    name = "noop"
    description = "noop"
    parameters = _NoopArgs
    label = "Noop"

    async def execute(self, tool_call_id, params, signal=None):
        return AgentToolResult(content=[TextContent(text="ok")])


@pytest.mark.asyncio
async def test_prompt_returns_result_and_accumulates_history():
    clear_providers()
    register_mock()
    mock = create_mock_model(responses=[{"content": ["hi"]}, {"content": ["again"]}])
    agent = Agent(model=mock, system_prompt=["sys"])
    seen = []
    agent.subscribe(lambda e: seen.append(e.type))

    r1 = await agent.prompt("hello")
    assert r1.reason is StopReason.COMPLETED
    assert "agent_start" in seen and "agent_end" in seen

    r2 = await agent.prompt("more")
    assert r2.reason is StopReason.COMPLETED
    roles = [m.role for m in agent.state.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert len(mock.calls) == 2
    assert len(mock.calls[1].messages) >= 3


@pytest.mark.asyncio
async def test_steer_injects_queued_message_into_next_turn():
    clear_providers()
    register_mock()

    holder: dict = {"n": 0}

    def handler(context):
        holder["n"] += 1
        if holder["n"] == 1:
            # steer mid-run: should surface to the model at the next turn boundary
            holder["agent"].steer(UserMessage(content="STEER-ME"))
            return {"content": [{"type": "toolCall", "name": "noop", "arguments": {}}]}
        return {"content": ["done"]}

    mock = create_mock_model(handler=handler)
    agent = Agent(model=mock, tools=[_NoopTool()])
    holder["agent"] = agent

    result = await agent.prompt("go")
    assert result.reason is StopReason.COMPLETED
    assert len(mock.calls) == 2

    # the model must SEE the steered message on the second turn's context
    turn2_user_texts = [
        m.content
        for m in mock.calls[1].messages
        if m.role == "user" and isinstance(m.content, str)
    ]
    assert "STEER-ME" in turn2_user_texts

    # and it persists in agent state (surfaced via produced)
    assert any(
        getattr(m, "role", None) == "user" and getattr(m, "content", None) == "STEER-ME"
        for m in agent.state.messages
    )
