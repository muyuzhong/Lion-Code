from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from lion_code.capabilities.memory import (
    MemoryTurnParticipant,
    create_memory_capability,
)
from lion_code.core.cancellation import CancellationToken
from lion_code.core.messages import AgentMessage, UserMessage
from lion_code.project_identity import ProjectIdentity
from lion_code.session_memory import SessionMemoryRepository
from lion_code.session_memory_coordinator import SessionMemoryCoordinator


@dataclass
class _Transcript:
    messages: list[AgentMessage]


class _NoticeSink:
    def emit(self, message: str, *, role: str = "info") -> None:
        del message, role


class _RecordingCoordinator:
    def __init__(self) -> None:
        self.begin_calls: list[str] = []
        self.finish_calls: list[tuple[str, int]] = []
        self.reset_calls = 0
        self.close_calls = 0
        self.project_calls: list[tuple[tuple[AgentMessage, ...], int | None]] = []

    def begin_user_turn(self, user_message: str) -> None:
        self.begin_calls.append(user_message)

    async def finish_user_turn(self, user_message: str, start_index: int) -> None:
        self.finish_calls.append((user_message, start_index))

    def reset_for_session(self) -> None:
        self.reset_calls += 1

    def project(self, messages, *, max_tokens):
        self.project_calls.append((tuple(messages), max_tokens))
        return [*messages, UserMessage(content="projected")]

    async def close(self) -> None:
        self.close_calls += 1


def test_memory_capability_uses_only_memory_slots() -> None:
    coordinator = _RecordingCoordinator()
    transcript = _Transcript([])

    spec = create_memory_capability(coordinator, transcript)

    assert spec.name == "memory"
    assert spec.tool_sources == ()
    assert spec.prompt_layers == ()
    assert len(spec.turn_participants) == 1
    assert len(spec.session_participants) == 1
    assert len(spec.projection_layers) == 1
    assert len(spec.resources) == 1


@pytest.mark.asyncio
async def test_turn_participant_keeps_transcript_boundary_private() -> None:
    coordinator = _RecordingCoordinator()
    transcript = _Transcript([UserMessage(content="prior")])
    participant = MemoryTurnParticipant(coordinator, transcript)

    await participant.before_turn("question")
    transcript.messages.append(UserMessage(content="question"))
    await participant.after_turn()
    await participant.after_turn()

    assert coordinator.begin_calls == ["question"]
    assert coordinator.finish_calls == [("question", 1)]


@pytest.mark.asyncio
async def test_session_projection_and_resource_slots_delegate() -> None:
    coordinator = _RecordingCoordinator()
    transcript = _Transcript([])
    spec = create_memory_capability(coordinator, transcript)

    projected = spec.projection_layers[0].project(
        [UserMessage(content="question")], max_tokens=100
    )
    await spec.session_participants[0].on_new_session()
    await spec.session_participants[0].on_restore_session()
    await spec.resources[0].close()

    assert projected[-1].text == "projected"
    assert coordinator.project_calls[0][1] == 100
    assert coordinator.reset_calls == 2
    assert coordinator.close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_finish_cancels_pending_prefetch(tmp_path) -> None:
    identity = ProjectIdentity(root=tmp_path.resolve(), key="test", is_git=False)
    cancellation = CancellationToken()
    cancellation.cancel()
    coordinator = SessionMemoryCoordinator(
        identity=identity,
        repository=SessionMemoryRepository(identity, storage_dir=tmp_path / "state"),
        transcript=_Transcript([]),
        cancellation=cancellation,
        load_project_context=lambda _identity: (),
        notices=_NoticeSink(),
        query=None,
        is_sub_agent=False,
    )
    memory_coordinator = coordinator.memory_coordinator
    memory_coordinator.cancel_pending = Mock(wraps=memory_coordinator.cancel_pending)

    await coordinator.finish_user_turn("question", 0)

    memory_coordinator.cancel_pending.assert_called_once_with()
