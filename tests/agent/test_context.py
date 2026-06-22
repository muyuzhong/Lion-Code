import pytest
from pydantic import BaseModel

from nanoagent.ai import UserMessage
from nanoagent.agent.context import assemble_context
from nanoagent.agent.messages import default_convert_to_llm
from nanoagent.agent.tools import AgentTool, AgentToolResult


class A(BaseModel):
    pass


class T(AgentTool):
    name = "t"
    description = "d"
    parameters = A
    label = "T"

    async def execute(self, tool_call_id, params, signal=None):
        return AgentToolResult()


@pytest.mark.asyncio
async def test_assemble_builds_wire_context():
    ctx = await assemble_context(
        system_prompt=["sys"],
        messages=[UserMessage(content="hi")],
        tools=[T()],
        convert_to_llm=default_convert_to_llm,
    )
    assert ctx.system_prompt == ["sys"]
    assert ctx.messages[0].role == "user"
    assert ctx.tools[0].name == "t"


@pytest.mark.asyncio
async def test_transform_context_runs_first():
    async def drop_all(messages, signal=None):
        return []

    ctx = await assemble_context(
        system_prompt=[],
        messages=[UserMessage(content="hi")],
        tools=[],
        convert_to_llm=default_convert_to_llm,
        transform_context=drop_all,
    )
    assert ctx.messages == []


@pytest.mark.asyncio
async def test_transform_context_receives_message_list_snapshot():
    original = [UserMessage(content="hi")]

    async def clear_received(messages, signal=None):
        messages.clear()
        return []

    await assemble_context(
        system_prompt=[],
        messages=original,
        tools=[],
        convert_to_llm=default_convert_to_llm,
        transform_context=clear_received,
    )

    assert len(original) == 1
