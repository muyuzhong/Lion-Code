"""Shared fakes for Core tests.

``FakeProvider`` is a scripted, signal-aware stand-in for ``ModelProvider``: it
replays one ``AssistantMessageEvent`` per ``stream_response`` call (a terminal
``AssistantDoneEvent`` / ``AssistantErrorEvent`` is enough to drive the loop), and
if the cancellation signal is set when a stream starts it emits
``AssistantErrorEvent(aborted)`` so the loop terminates like a real provider whose
stream was cancelled.

It also records what each model request received (system, messages, tool names)
so dynamic-configuration tests can assert per-turn behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from lion_code.core.messages import AssistantMessage
from lion_code.core.provider_events import AssistantErrorEvent, AssistantMessageEvent


class FakeProvider:
    def __init__(self, events) -> None:
        self._events = list(events)
        self._index = 0
        self.call_count = 0
        self.received_systems: list[str] = []
        self.received_messages: list[list] = []
        self.received_tools: list[list[str]] = []
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    def stream_response(
        self, *, model, system, messages, tools, signal=None
    ) -> AsyncIterator[AssistantMessageEvent]:
        self.call_count += 1
        self.received_systems.append(system)
        self.received_messages.append(list(messages))
        self.received_tools.append([tool.name for tool in tools])
        return self._gen(signal)

    async def _gen(self, signal):
        if signal is not None and signal.is_cancelled():
            yield AssistantErrorEvent(
                reason="aborted",
                error=AssistantMessage(model="fake", content=[], stop_reason="aborted"),
            )
            return
        if self._index >= len(self._events):
            raise AssertionError(
                f"FakeProvider scripted events exhausted after {self._index} call(s)"
            )
        event = self._events[self._index]
        self._index += 1
        yield event
