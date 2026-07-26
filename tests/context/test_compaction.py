from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from lion_code.context import ProviderContextCompactor, SUMMARY_SYSTEM_PROMPT
from lion_code.core import AssistantMessage, TextContent, UserMessage
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
)


class _RecordingProvider:
    def __init__(self, event: AssistantMessageEvent) -> None:
        self.event = event
        self.calls = []

    def stream_response(
        self, *, model, system, messages, tools, signal=None
    ) -> AsyncIterator[AssistantMessageEvent]:
        self.calls.append((model, system, messages, tools, signal))

        async def stream():
            yield self.event

        return stream()


@pytest.mark.asyncio
async def test_provider_compactor_uses_canonical_stream_without_mutating_history() -> None:
    provider = _RecordingProvider(
        AssistantDoneEvent(
            reason="stop",
            message=AssistantMessage(content=[TextContent(text="  concise summary  ")]),
        )
    )
    messages = (UserMessage(content="original"),)
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")

    summary = await compactor.summarize(messages)

    assert summary == "concise summary"
    assert messages[0].text == "original"
    model, system, projected, tools, signal = provider.calls[0]
    assert model == "fake"
    assert system == SUMMARY_SYSTEM_PROMPT
    assert projected[0] is not messages[0]
    assert "Summarize" in projected[-1].text
    assert tools == []
    assert signal is None


@pytest.mark.asyncio
async def test_provider_compactor_surfaces_provider_failure() -> None:
    provider = _RecordingProvider(
        AssistantErrorEvent(
            reason="error",
            error=AssistantMessage(stop_reason="error", error_message="failed"),
        )
    )
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")

    with pytest.raises(RuntimeError, match="failed"):
        await compactor.summarize((UserMessage(content="original"),))
