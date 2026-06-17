import pytest

from nanoagent.ai import UserMessage
from nanoagent.ai.provider import clear_providers
from nanoagent.ai.providers.mock import create_mock_model, register_mock
from nanoagent.agent.loop import AgentLoopConfig, agent_loop
from nanoagent.agent.result import StopReason


@pytest.mark.asyncio
async def test_text_only_turn_completes():
    clear_providers()
    register_mock()
    mock = create_mock_model(responses=[{"content": ["hi there"]}])
    cfg = AgentLoopConfig(model=mock)
    events = [
        e
        async for e in agent_loop(
            prompts=[UserMessage(content="hello")],
            system_prompt=["sys"],
            messages=[],
            tools=[],
            config=cfg,
        )
    ]
    assert events[0].type == "agent_start"
    end = events[-1]
    assert end.type == "agent_end"
    assert end.result.reason is StopReason.COMPLETED
    assert end.messages[-1].role == "assistant"
    assert end.messages[-1].content[0].text == "hi there"
    assert end.result.final_message_id == end.messages[-1].id
