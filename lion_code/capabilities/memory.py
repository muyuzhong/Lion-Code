"""Memory Capability：把 Session Memory 接入通用生命周期与投影 slot。"""

from __future__ import annotations

from collections.abc import Sequence

from lion_code.core.messages import AgentMessage
from lion_code.domain_ports import TranscriptView
from lion_code.session_memory_coordinator import SessionMemoryCoordinator

from .types import CapabilitySpec


class MemoryTurnParticipant:
    """在压缩后的 transcript 边界驱动一轮 Memory 状态。"""

    def __init__(
        self,
        coordinator: SessionMemoryCoordinator,
        transcript: TranscriptView,
    ) -> None:
        self._coordinator = coordinator
        self._transcript = transcript
        self._turn_start_index: int | None = None
        self._user_message: str | None = None

    async def before_turn(self, user_message: str) -> None:
        self._turn_start_index = len(self._transcript.messages)
        self._user_message = user_message
        self._coordinator.begin_user_turn(user_message)

    async def after_turn(self) -> None:
        start_index = self._turn_start_index
        user_message = self._user_message
        self._turn_start_index = None
        self._user_message = None
        if start_index is None or user_message is None:
            return
        await self._coordinator.finish_user_turn(user_message, start_index)


class MemorySessionParticipant:
    """在 clear/restore 边界重置并重载 Memory 运行态。"""

    def __init__(self, coordinator: SessionMemoryCoordinator) -> None:
        self._coordinator = coordinator

    async def on_new_session(self) -> None:
        self._coordinator.reset_for_session()

    async def on_restore_session(self) -> None:
        self._coordinator.reset_for_session()


class MemoryProjectionLayer:
    """把 `<relevant-memory>` 只注入当前 Provider 消息投影。"""

    layer_id = "memory"

    def __init__(self, coordinator: SessionMemoryCoordinator) -> None:
        self._coordinator = coordinator

    def project(
        self,
        messages: Sequence[AgentMessage],
        *,
        max_tokens: int | None,
    ) -> list[AgentMessage]:
        return self._coordinator.project(messages, max_tokens=max_tokens)


class MemoryResource:
    """拥有 Memory 预取任务的异步释放边界。"""

    def __init__(self, coordinator: SessionMemoryCoordinator) -> None:
        self._coordinator = coordinator

    async def close(self) -> None:
        await self._coordinator.close()


def create_memory_capability(
    coordinator: SessionMemoryCoordinator,
    transcript: TranscriptView,
) -> CapabilitySpec:
    """返回只经通用 slot 接线的 Memory Capability。"""

    return CapabilitySpec(
        name="memory",
        projection_layers=(MemoryProjectionLayer(coordinator),),
        turn_participants=(MemoryTurnParticipant(coordinator, transcript),),
        session_participants=(MemorySessionParticipant(coordinator),),
        resources=(MemoryResource(coordinator),),
    )
