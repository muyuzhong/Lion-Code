"""为已注册 Capability 提供通用生命周期分发。"""

from __future__ import annotations

from typing import Protocol

from lion_code.core.messages import AgentMessage

from .registry import CapabilityRegistry


class CapabilityLifecycle(Protocol):
    """Runtime 与 SessionLifecycle 共用的生命周期端口。"""

    async def before_turn(self, user_message: str) -> None: ...

    async def after_turn(self) -> None: ...

    async def on_new_session(self) -> None: ...

    async def on_restore_session(self) -> None: ...

    async def close(self) -> None: ...

    def project_context(
        self,
        messages: list[AgentMessage],
        *,
        max_tokens: int | None,
    ) -> list[AgentMessage]: ...


class CapabilityRuntime:
    """仅基于 Registry 分发参与者，不暴露 Capability 查找。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        self._closed = False

    async def before_turn(self, user_message: str) -> None:
        for participant in self._registry.turn_participants:
            await participant.before_turn(user_message)

    async def after_turn(self) -> None:
        for participant in self._registry.turn_participants:
            await participant.after_turn()

    async def on_new_session(self) -> None:
        for participant in self._registry.session_participants:
            await participant.on_new_session()

    async def on_restore_session(self) -> None:
        for participant in self._registry.session_participants:
            await participant.on_restore_session()

    def project_context(
        self,
        messages: list[AgentMessage],
        *,
        max_tokens: int | None,
    ) -> list[AgentMessage]:
        projected = list(messages)
        for layer in self._registry.projection_layers:
            projected = layer.project(projected, max_tokens=max_tokens)
        return projected

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._registry.close_all()
