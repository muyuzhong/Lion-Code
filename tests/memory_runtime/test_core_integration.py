from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest

import lion_code.memory_runtime.coordinator as coordinator_module
from lion_code.agent import Agent
from lion_code.core import AssistantMessage, TextContent, ToolCall
from lion_code.core.provider_events import AssistantDoneEvent, AssistantMessageEvent
from lion_code.memory import MemoryPrefetch, RelevantMemory
from lion_code.memory_runtime import MemoryCoordinator, MemoryOverlay
from lion_code.project_identity import ProjectIdentity
from lion_code.prompt import ProjectContextFile
from lion_code.session_memory import SessionMemory, SessionMemoryRepository
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult

_REHOME = (
    "PR1 Bare Agent Extraction: turn-driven Memory 自动行为已从 Core 生命周期移除，"
    "待 Capability re-home PR 恢复"
)


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
    project_context: tuple[ProjectContextFile, ...] = (),
    project_identity: ProjectIdentity | None = None,
    session_memory_repository: SessionMemoryRepository | None = None,
) -> tuple[Agent, FakeProvider, SessionRepository]:
    fake = FakeProvider(events)
    repository = SessionRepository(tmp_path)
    identity = project_identity or ProjectIdentity(
        root=tmp_path.resolve(),
        key=f"test-{tmp_path.name}",
        is_git=False,
    )
    memory_repository = session_memory_repository or SessionMemoryRepository(
        identity,
        storage_dir=tmp_path / "session-memory",
    )
    monkeypatch.setattr("lion_code.agent.create_provider", lambda **_kwargs: fake)
    monkeypatch.setattr(
        "lion_code.agent.load_project_context_files",
        lambda **_kwargs: project_context,
    )
    monkeypatch.setattr(
        "lion_code.agent.resolve_project_identity",
        lambda _cwd: identity,
    )
    agent = Agent(
        api_base="https://example.test/v1",
        api_key="test-key",
        custom_system_prompt="test",
        tool_registry=registry or ToolRegistry(),
        session_repository=repository,
        session_memory_repository=memory_repository,
        terminal_output=False,
    )

    async def no_semantic_patch(*_args, **_kwargs) -> dict[str, object]:
        return {}

    monkeypatch.setattr(agent, "_extract_session_memory_semantics", no_semantic_patch)
    agent._memory_coordinator = MemoryCoordinator(query_service=None)
    return agent, fake, repository


def _result_tool(name: str, content: str, *, is_error: bool = False) -> LionTool:
    async def execute(_ctx, _id, _arguments, _on_update):
        return ToolResult(content=content, is_error=is_error)

    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object"},
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True),
    )


def _evidence_tool_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[
                ToolCall(
                    id="write",
                    name="write_file",
                    arguments={"file_path": "lion_code/session_memory.py"},
                ),
                ToolCall(
                    id="test",
                    name="run_shell",
                    arguments={"command": "python -m pytest -q"},
                ),
            ],
            stop_reason="toolUse",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.skip(reason=_REHOME)
async def test_overlay_reaches_provider_but_not_harness_or_jsonl(
    monkeypatch, tmp_path
) -> None:
    agent, fake, repository = _make_agent(monkeypatch, tmp_path, [_stop_event()])
    overlay = MemoryOverlay("project.md", "remember this", 13)
    agent._memory_coordinator._active[overlay.path] = overlay

    await agent.chat("question")

    assert "<relevant-memory>" in fake.received_messages[0][-1].text
    assert all(
        "<relevant-memory>" not in message.text
        for message in agent._core_runtime.messages
    )
    state = await repository.load(agent.session_id)
    assert state is not None
    assert all("<relevant-memory>" not in message.text for message in state.messages)
    assert "<relevant-memory>" not in repository.storage_for(
        agent.session_id
    ).path.read_text(encoding="utf-8")
    assert agent._last_memory_injection.injected_paths == (
        str(agent._session_memory_repository.path),
        "project.md",
    )
    await agent.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason=_REHOME)
async def test_project_overlay_reaches_provider_but_not_harness_or_jsonl(
    monkeypatch, tmp_path
) -> None:
    context = (ProjectContextFile("C:/repo/AGENTS.md", "run focused tests"),)
    agent, fake, repository = _make_agent(
        monkeypatch,
        tmp_path,
        [_stop_event()],
        project_context=context,
    )

    await agent.chat("question")

    provider_text = fake.received_messages[0][-1].text
    assert "<project-memory>" in provider_text
    assert "<session-memory>" in provider_text
    assert "run focused tests" in provider_text
    assert all(
        "<relevant-memory>" not in message.text
        for message in agent._core_runtime.messages
    )
    state = await repository.load(agent.session_id)
    assert state is not None
    assert all("<relevant-memory>" not in message.text for message in state.messages)
    assert agent._last_memory_injection.injected_paths == (
        "C:/repo/AGENTS.md",
        str(agent._session_memory_repository.path),
    )
    await agent.close()


@pytest.mark.asyncio
async def test_clear_and_restore_keep_current_project_session_memory(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    identity = ProjectIdentity(root=root.resolve(), key="project", is_git=True)
    memory_repository = SessionMemoryRepository(
        identity,
        storage_dir=tmp_path / "project-state",
    )
    saved = memory_repository.save(
        SessionMemory(
            project_root=str(identity.root),
            current_goal="实现短期记忆",
            active_task="持久化状态",
            next_step="验证 clear",
        )
    )
    agent, _, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [_stop_event()],
        project_identity=identity,
        session_memory_repository=memory_repository,
    )
    first_session_id = agent.session_id

    assert agent.session_memory == saved
    await agent.chat("first question")
    saved_after_turn = agent.session_memory
    await agent.clear_history()

    assert agent.session_id != first_session_id
    assert agent.session_memory == saved_after_turn
    assert memory_repository.load() == saved_after_turn
    assert await agent.restore_core_session(first_session_id)
    assert agent.session_memory == saved_after_turn
    await agent.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason=_REHOME)
async def test_corrupt_session_memory_stays_visible_without_clear_overwrite(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    identity = ProjectIdentity(root=root.resolve(), key="project", is_git=True)
    memory_repository = SessionMemoryRepository(
        identity,
        storage_dir=tmp_path / "project-state",
    )
    saved = memory_repository.save(
        SessionMemory(project_root=str(identity.root), current_goal="valid state")
    )
    agent, _, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [],
        project_identity=identity,
        session_memory_repository=memory_repository,
    )
    memory_repository.path.write_text("{broken", encoding="utf-8")
    original = memory_repository.path.read_bytes()

    await agent.clear_history()

    assert agent.session_memory == saved
    assert agent.session_memory_error is not None
    assert memory_repository.path.read_bytes() == original
    await agent.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason=_REHOME)
async def test_turn_end_merges_tool_evidence_before_semantic_patch(
    monkeypatch, tmp_path
) -> None:
    registry = ToolRegistry()
    registry.register(_result_tool("write_file", "Successfully wrote file"))
    registry.register(_result_tool("run_shell", "Command failed (exit code 1)"))
    agent, _, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [_evidence_tool_event(), _stop_event()],
        registry,
    )

    async def semantic_patch(*_args, **_kwargs) -> dict[str, object]:
        return {
            "currentGoal": "完成短期记忆",
            "activeTask": "记录工具事实",
            "pending": ["运行完整回归"],
            "relevantFiles": ["model-invented.py"],
            "verification": ["model-invented verification"],
        }

    monkeypatch.setattr(agent, "_extract_session_memory_semantics", semantic_patch)

    await agent.chat("记录这轮进展")

    assert agent.session_memory is not None
    assert agent.session_memory.relevant_files == ("lion_code/session_memory.py",)
    assert agent.session_memory.verification == ("python -m pytest -q: failed",)
    assert any(
        item.startswith("run_shell failed:") for item in agent.session_memory.blockers
    )
    assert agent.session_memory.current_goal == "完成短期记忆"
    assert agent.session_memory.active_task == "记录工具事实"
    assert agent.session_memory.pending == ("运行完整回归",)
    await agent.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason=_REHOME)
async def test_semantic_patch_failure_still_saves_tool_evidence(
    monkeypatch, tmp_path
) -> None:
    registry = ToolRegistry()
    registry.register(_result_tool("write_file", "Successfully wrote file"))
    registry.register(_result_tool("run_shell", "Command failed (exit code 1)"))
    agent, _, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [_evidence_tool_event(), _stop_event()],
        registry,
    )

    async def unavailable_semantic_patch(*_args, **_kwargs) -> dict[str, object]:
        raise RuntimeError("semantic memory unavailable")

    monkeypatch.setattr(
        agent,
        "_extract_session_memory_semantics",
        unavailable_semantic_patch,
    )

    await agent.chat("记录这轮进展")

    assert agent.session_memory is not None
    assert agent.session_memory.relevant_files == ("lion_code/session_memory.py",)
    assert agent.session_memory.verification == ("python -m pytest -q: failed",)
    await agent.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason=_REHOME)
async def test_current_turn_prefetch_waits_until_next_user_turn_and_snapshot_is_fixed(
    monkeypatch, tmp_path
) -> None:
    registry = ToolRegistry()
    registry.register(_echo_tool())
    agent, fake, _ = _make_agent(
        monkeypatch,
        tmp_path,
        [_tool_event(), _stop_event(), _stop_event("next turn")],
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

    first_overlay = fake.received_messages[0][-1].text
    second_overlay = fake.received_messages[1][-1].text
    first_overlay = first_overlay[first_overlay.index("<relevant-memory>") :]
    second_overlay = second_overlay[second_overlay.index("<relevant-memory>") :]
    assert first_overlay == second_overlay
    assert "<auto-memory>" not in first_overlay

    await agent.chat("next question")

    assert "<auto-memory>" in fake.received_messages[2][-1].text
    assert "current memory" in fake.received_messages[2][-1].text
    assert all(
        "<relevant-memory>" not in message.text
        for message in agent._core_runtime.messages
    )
    await agent.close()


@pytest.mark.asyncio
async def test_prefetch_failure_does_not_interrupt_tool_loop(
    monkeypatch, tmp_path
) -> None:
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
@pytest.mark.skip(reason=_REHOME)
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
async def test_sub_agent_on_core_skips_memory_prefetch(monkeypatch, tmp_path) -> None:
    """子 Agent 也走 Core(阶段4-C7),但 Memory 召回仍只服务主会话。"""
    fake = FakeProvider([_stop_event("sub done")])
    with patch("lion_code.agent.create_provider", return_value=fake):
        agent = Agent(
            api_base="https://example.test/v1",
            api_key="test-key",
            custom_system_prompt="test",
            is_sub_agent=True,
            session_repository=SessionRepository(tmp_path),
        )

    with patch.object(
        agent._memory_coordinator,
        "begin_turn",
        wraps=agent._memory_coordinator.begin_turn,
    ) as begin_turn:
        await agent.chat("sub question")

    begin_turn.assert_not_called()
    assert agent._core_runtime is not None
    assert agent._core_runtime.messages[-1].text == "sub done"
    # 子 Agent 不落盘会话。
    assert await SessionRepository(tmp_path).list_sessions() == []
    await agent.close()
