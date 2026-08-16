"""PR6 MetaAgent 的 zero-extension 与显式 Coding Harness 验收。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from core.fakes import FakeProvider

from lion_code import MetaAgent, build_meta_agent
from lion_code.context import ContextCompactor
from lion_code.core import (
    AssistantMessage,
    CancelledEvent,
    CompactionCompletedEvent,
    CompactionStartedEvent,
    MessageEndEvent,
    MessageStartEvent,
    TextContent,
    ToolCall,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
)
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.builtin import create_builtin_tools
from lion_code.tooling.execution import LocalCommandExecutionBackend


def _done(text: str) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
        ),
    )


def _tool_call(name: str, arguments: dict) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[ToolCall(id="call-1", name=name, arguments=arguments)],
            stop_reason="toolUse",
        ),
    )


class _StaticCompactor(ContextCompactor):
    async def summarize(self, _messages) -> str:
        return "summary"


class _BlockingCompactor(ContextCompactor):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def summarize(self, _messages) -> str:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _FlowProvider(FakeProvider):
    def __init__(self, events) -> None:
        super().__init__(events)
        self.waiting = asyncio.Event()
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1
        await super().aclose()

    def stream_response(
        self, *, model, system, messages, tools, signal=None
    ) -> AsyncIterator[AssistantMessageEvent]:
        if self._index < len(self._events) and self._events[self._index] == "wait":
            self.call_count += 1
            self.received_systems.append(system)
            self.received_messages.append(list(messages))
            self.received_tools.append([tool.name for tool in tools])
            self.received_signals.append(signal)
            self._index += 1
            return self._wait_for_cancel(signal)
        return super().stream_response(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            signal=signal,
        )

    async def _wait_for_cancel(self, signal):
        self.waiting.set()
        while signal is not None and not signal.is_cancelled():
            await asyncio.sleep(0)
        yield AssistantErrorEvent(
            reason="aborted",
            error=AssistantMessage(model="fake", content=[], stop_reason="aborted"),
        )


@pytest.mark.asyncio
async def test_zero_extension_zero_tool_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([_done("hello")])
    agent = build_meta_agent(
        provider=provider,
        tools=[],
        session_repository=SessionRepository(tmp_path / "sessions"),
    )

    result = await agent.run("hello")

    assert result.final_text == "hello"
    assert [message.role for message in agent.messages] == ["user", "assistant"]
    assert provider.received_tools == [[]]
    assert provider.received_systems == ["You are a helpful assistant."]
    assert agent._capability_registry.names == ()
    assert agent.usage.responses == 1
    assert agent.budget.max_cost_usd is None
    await agent.close()


@pytest.mark.asyncio
async def test_empty_system_prompt_stays_meta_neutral(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([_done("hello")])
    agent = build_meta_agent(
        provider=provider,
        tools=[],
        system_prompt="",
        session_repository=SessionRepository(tmp_path / "sessions"),
    )

    await agent.run("hello")

    assert provider.received_systems == ["You are a helpful assistant."]
    await agent.close()


@pytest.mark.asyncio
async def test_coding_harness_is_explicit_tool_composition(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sample.txt").write_text("from workspace", encoding="utf-8")
    coding_names = {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "grep_search",
        "run_shell",
    }
    coding_tools = [
        tool
        for tool in create_builtin_tools(LocalCommandExecutionBackend())
        if tool.name in coding_names
    ]
    provider = FakeProvider(
        [_tool_call("read_file", {"file_path": "sample.txt"}), _done("finished")]
    )
    agent = build_meta_agent(
        provider=provider,
        tools=coding_tools,
        permission_mode="bypassPermissions",
        session_repository=SessionRepository(tmp_path / "sessions"),
    )
    events = []
    agent.subscribe(events.append)

    result = await agent.run("read the file")

    assert result.final_text == "finished"
    assert [message.role for message in agent.messages] == [
        "user",
        "assistant",
        "toolResult",
        "assistant",
    ]
    assert "from workspace" in agent.messages[2].text
    assert set(provider.received_tools[0]) == coding_names
    assert any(isinstance(event, TurnStartEvent) for event in events)
    assert any(isinstance(event, MessageStartEvent) for event in events)
    assert any(isinstance(event, MessageEndEvent) for event in events)
    assert any(isinstance(event, ToolExecutionStartEvent) for event in events)
    assert any(isinstance(event, ToolExecutionEndEvent) for event in events)
    assert any(isinstance(event, TurnEndEvent) for event in events)
    await agent.close()


@pytest.mark.asyncio
async def test_strong_negative_flow_never_constructs_advanced_features(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    import lion_code.composition.agent_builder as builder

    def forbidden(*_args, **_kwargs):
        raise AssertionError("advanced Feature constructor called")

    for name in (
        "ChildAgentConfig",
        "NoticeSinkAdapter",
        "PlanHost",
        "PlanRuntime",
        "PlanState",
        "ProviderTextQueryService",
        "SessionMemoryCoordinator",
        "SkillRuntime",
        "SubagentStatusSink",
        "SubagentExecutor",
        "SubagentFactory",
        "create_builtin_tools",
        "create_internal_tools",
        "create_plan_capability",
        "create_provider",
        "create_skill_capability",
        "create_subagent_capability",
        "load_pre_tool_use_hooks",
    ):
        monkeypatch.setattr(builder, name, forbidden)

    read_file = next(
        tool
        for tool in create_builtin_tools(LocalCommandExecutionBackend())
        if tool.name == "read_file"
    )
    (tmp_path / "sample.txt").write_text("negative flow", encoding="utf-8")
    provider = _FlowProvider(
        [
            _done("plain"),
            _tool_call("read_file", {"file_path": "sample.txt"}),
            _done("tool done"),
            "wait",
        ]
    )
    repository = SessionRepository(tmp_path / "sessions")
    agent = build_meta_agent(
        provider=provider,
        tools=[read_file],
        permission_mode="bypassPermissions",
        session_repository=repository,
        context_compactor=_StaticCompactor(),
    )
    events = []
    agent.subscribe(events.append)

    assert (await agent.run("plain")).final_text == "plain"
    assert (await agent.run("tool")).final_text == "tool done"
    saved_session_id = agent.session_id
    await agent.compact()
    assert [
        event.reason for event in events if isinstance(event, CompactionStartedEvent)
    ] == ["manual"]
    assert [
        (event.reason, event.aborted)
        for event in events
        if isinstance(event, CompactionCompletedEvent)
    ] == [("manual", False)]

    await agent.new_session()
    assert agent.messages == ()
    assert await agent.restore(saved_session_id) is True
    assert agent.messages

    task = asyncio.create_task(agent.run("wait"))
    await provider.waiting.wait()
    agent.cancel()
    result = await task
    assert result.stop_reason == "aborted"
    assert any(isinstance(event, CancelledEvent) for event in events)

    await agent.close()
    await agent.close()
    assert provider.close_count == 1


@pytest.mark.asyncio
async def test_direct_provider_can_use_explicit_reconfiguration_factory(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    provider = _FlowProvider([_done("initial")])
    replacement = _FlowProvider([_done("replacement")])
    factory_calls = []

    def provider_factory(**kwargs):
        factory_calls.append(kwargs)
        return replacement

    agent = build_meta_agent(
        provider=provider,
        provider_factory=provider_factory,
        tools=[],
        session_repository=SessionRepository(tmp_path / "sessions"),
    )

    assert agent.provider is provider
    agent.configure_provider(model="meta-next")
    assert agent.provider is provider
    agent.set_thinking_level("low")
    assert agent.provider is replacement
    assert len(factory_calls) == 1
    assert factory_calls[0]["thinking_level"] == "low"
    assert (await agent.run("hello")).final_text == "replacement"
    await agent.close()


@pytest.mark.asyncio
async def test_compaction_cancellation_emits_aborted_completion(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    compactor = _BlockingCompactor()
    provider = FakeProvider([_done("ready"), _done("ready again")])
    agent = build_meta_agent(
        provider=provider,
        tools=[],
        session_repository=SessionRepository(tmp_path / "sessions"),
        context_compactor=compactor,
    )
    events = []
    agent.subscribe(events.append)
    await agent.run("hello")
    await agent.run("again")

    task = asyncio.create_task(agent.compact())
    started = asyncio.create_task(compactor.started.wait())
    done, _ = await asyncio.wait(
        (task, started), timeout=2, return_when=asyncio.FIRST_COMPLETED
    )
    assert started in done, task.exception() if task in done else "compaction stalled"
    agent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [
        event.reason for event in events if isinstance(event, CompactionStartedEvent)
    ] == ["manual"]
    assert [
        (event.reason, event.aborted)
        for event in events
        if isinstance(event, CompactionCompletedEvent)
    ] == [("manual", True)]
    await agent.close()


def test_meta_agent_public_surface_is_feature_neutral() -> None:
    public = {name for name in dir(MetaAgent) if not name.startswith("_")}
    assert public == {
        "available_thinking_levels",
        "budget",
        "cancel",
        "cancelled",
        "chat",
        "close",
        "compact",
        "configure_provider",
        "continue_",
        "conversation",
        "cycle_thinking_level",
        "follow_up",
        "messages",
        "model",
        "new_session",
        "permission_mode",
        "prompt",
        "provider",
        "provider_config",
        "restore",
        "run",
        "run_once",
        "session_id",
        "set_thinking",
        "set_thinking_level",
        "steer",
        "subscribe",
        "thinking",
        "thinking_level",
        "usage",
    }
    forbidden = (
        "autonom",
        "dream",
        "goal",
        "learn",
        "memory",
        "plan",
        "skill",
        "subagent",
    )
    assert not any(marker in name.casefold() for name in public for marker in forbidden)
