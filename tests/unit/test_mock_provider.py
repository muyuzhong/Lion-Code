"""剧本驱动 MockProvider 测试。"""

import pytest

from providers.base import (
    MessageEnd,
    MessageStart,
    ModelRequest,
    RateLimitError,
    TextDelta,
)
from providers.mock import MockProvider


def make_request():
    return ModelRequest(system="s", messages=[], tools=[], model="mock-model")


async def collect(provider):
    return [event async for event in provider.stream(make_request())]


async def test_text_turn_replay():
    provider = MockProvider([MockProvider.text_turn("你好")])
    events = await collect(provider)
    assert isinstance(events[0], MessageStart)
    assert isinstance(events[1], TextDelta) and events[1].text == "你好"
    assert isinstance(events[-1], MessageEnd)
    assert events[-1].stop_reason == "end_turn"


async def test_tool_turn_replay():
    provider = MockProvider([MockProvider.tool_turn("bash", {"cmd": "ls"}, tool_id="t1")])
    events = await collect(provider)
    assert [type(event).__name__ for event in events] == [
        "MessageStart", "ToolUseStart", "ToolInputDelta", "ToolUseEnd", "MessageEnd"
    ]
    assert events[1].id == "t1" and events[1].name == "bash"
    assert events[2].id == "t1"
    assert events[-1].stop_reason == "tool_use"


async def test_exception_entry_raises():
    provider = MockProvider([RateLimitError(retry_after=1.0)])
    with pytest.raises(RateLimitError):
        await collect(provider)


async def test_records_requests_and_exhausts():
    provider = MockProvider([MockProvider.text_turn("a")])
    await collect(provider)
    assert len(provider.requests) == 1
    with pytest.raises(AssertionError):
        await collect(provider)
