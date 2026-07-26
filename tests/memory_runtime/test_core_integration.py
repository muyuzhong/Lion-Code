from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import lion_code.memory_runtime.coordinator as coordinator_module
from lion_code.agent import Agent
from lion_code.core import AssistantMessage, TextContent, ToolCall
from lion_code.core.provider_events import AssistantDoneEvent, AssistantMessageEvent
from lion_code.memory import MemoryPrefetch, RelevantMemory
from lion_code.memory_runtime import MemoryCoordinator, MemoryOverlay
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


class _QueryService:
    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str:
        return "{}"


class FakeProvider:
    def __init__(self, events: list[AssistantDoneEvent]) -> None:
        self._events = iter(events)
        self.call_count = 0
        self.received_messages: list[list] = []

    def stream_response(
        self, *, model, system, messages, tools, signal=None
    ) -> AsyncIterator[AssistantMessageEvent]:
        self.call_count += 1
        self.received_messages.append(list(messages))
        return self._stream()

    async def _stream(self) -> AsyncIterator[AssistantMessageEvent]:
        yield next(self._events)


def _stop_event(text: str = "done") -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
        ),
    )


def _tool_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[ToolCall(id="call-1", name="echo", arguments={})],
            stop_reason="toolUse",
        ),
    )


def _echo_tool() -> LionTool:
    async def execute(_ctx, _id, _arguments, _on_update):
        await asyncio.sleep(0)
        return ToolResult(content="echoed")

    return LionTool(
        name="echo",
        label="Echo",
        description="echo",
        parameters={"type": "object"},
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True),
    )


def _make_agent(
    monkeypatch,
    tmp_path: Path,
    events: list[AssistantDoneEvent],
    registry: ToolRegistry | None = None,
) -> tuple[Agent, FakeProvider, SessionRepository]:
    fake = FakeProvider(events)
    repository = SessionRepository(tmp_path)
    monkeypatch.setenv("LION_CORE_RUNTIME", "1")
    monkeypatch.setattr("lion_code.agent.create_provider", lambda **_kwargs: fake)
    agent = Agent(
        api_base="https://example.test/v1",
        api_key="test-key",
        custom_system_prompt="test",
        tool_registry=registry or ToolRegistry(),
        session_repository=repository,
    )
    agent._mcp_initialized = True
    agent._memory_coordinator = MemoryCoordinator(query_service=None)
    return agent, fake, repository


@pytest.mark.asyncio
async def test_overlay_reaches_provider_but_not_harness_or_jsonl(
    monkeypatch, tmp_path
) -> None:
    agent, fake, repository = _make_agent(monkeypatch, tmp_path, [_stop_event()])
    overlay = MemoryOverlay("project.md", "remember this", 13)
    agent._memory_coordinator._active[overlay.path] = overlay

    await agent.chat("question")

    assert "<relevant-memory>" in fake.received_messages[0][-1].text
    assert all("<relevant-memory>" not in message.text for message in agent._core_runtime.messages)
    state = await repository.load(agent.session_id)
    assert state is not None
    assert all("<relevant-memory>" not in message.text for message in state.messages)
    assert "<relevant-memory>" not in repository.storage_for(agent.session_id).path.read_text(
        encoding="utf-8"
    )
    assert agent._last_memory_injection.injected_paths == ("project.md",)
    await agent.close()


@pytest.mark.asyncio
async def test_current_turn_prefetch_is_visible_on_second_model_call(
    monkeypatch, tmp_path
) -> None:
    registry = ToolRegistry()
    registry.register(_echo_tool())
    agent, fake, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [_tool_event(), _stop_event()],
        registry,
    )
    agent._memory_coordinator = MemoryCoordinator(query_service=_QueryService())

    async def complete() -> list[RelevantMemory]:
        return [RelevantMemory("current.md", "current memory", 0, "")]

    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: MemoryPrefetch(asyncio.create_task(complete())),
    )

    await agent.chat("current question")

    assert "<relevant-memory>" not in "".join(
        message.text for message in fake.received_messages[0]
    )
    assert "<relevant-memory>" in "".join(
        message.text for message in fake.received_messages[1]
    )
    assert all("<relevant-memory>" not in message.text for message in agent._core_runtime.messages)
    await agent.close()


@pytest.mark.asyncio
async def test_prefetch_failure_does_not_interrupt_tool_loop(monkeypatch, tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(_echo_tool())
    agent, fake, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [_tool_event(), _stop_event("after failure")],
        registry,
    )
    agent._memory_coordinator = MemoryCoordinator(query_service=_QueryService())

    async def fail() -> list[RelevantMemory]:
        raise RuntimeError("memory unavailable")

    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: MemoryPrefetch(asyncio.create_task(fail())),
    )

    await agent.chat("current question")

    assert fake.call_count == 2
    assert agent._core_runtime.messages[-1].text == "after failure"
    await agent.close()


@pytest.mark.asyncio
async def test_clear_and_restore_drop_previous_overlay(monkeypatch, tmp_path) -> None:
    first, _, repository = _make_agent(monkeypatch, tmp_path, [_stop_event()])
    await first.chat("first question")

    second, _, _ = _make_agent(monkeypatch, tmp_path, [])
    old = MemoryOverlay("old.md", "old", 3)
    second._memory_coordinator._active[old.path] = old
    assert await second.restore_core_session(first.session_id)
    assert second._memory_coordinator.active_overlays == ()

    second._memory_coordinator._active[old.path] = old
    await second.clear_history()
    assert second._memory_coordinator.active_overlays == ()
    assert repository.storage_for(first.session_id).path.exists()
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_sub_agent_keeps_legacy_openai_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LION_CORE_RUNTIME", "1")
    agent = Agent(
        api_base="https://example.test/v1",
        api_key="test-key",
        custom_system_prompt="test",
        is_sub_agent=True,
        session_repository=SessionRepository(tmp_path),
    )
    agent._mcp_initialized = True

    with (
        patch.object(agent, "_chat_openai", new_callable=AsyncMock) as old_chat,
        patch.object(agent, "_auto_save"),
    ):
        await agent.chat("legacy question")

    assert agent._core_runtime is None
    old_chat.assert_awaited_once_with("legacy question")
    await agent.close()
