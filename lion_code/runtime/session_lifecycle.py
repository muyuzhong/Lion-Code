"""会话生命周期协调：clear/restore/compact/close。

从 ``AgentRuntimeCoordinator`` 拆出，收敛 JSONL 会话的创建、恢复、压缩与关闭。
不复制 coordinator 的 ``reset_core_observers`` / ``reset_session_usage``
逻辑，而是通过持有 coordinator 引用调用。
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..capabilities import CapabilityLifecycle
    from .agent import (
        AgentRuntimeCoordinator,
        LionAgentRuntime,
        RuntimeIdentityHost,
        SessionStateHost,
    )


class SessionLifecycle:
    """拥有 clear/restore/compact/close 的会话生命周期协调。"""

    def __init__(
        self,
        coordinator: AgentRuntimeCoordinator,
        capabilities: CapabilityLifecycle,
    ) -> None:
        self._coord = coordinator
        self._capabilities = capabilities

    @property
    def _identity(self) -> RuntimeIdentityHost:
        return self._coord._identity

    @property
    def _session(self) -> SessionStateHost:
        return self._coord._session

    @property
    def _runtime(self) -> LionAgentRuntime:
        return self._coord._runtime

    async def clear_history(self) -> None:
        """创建新的 JSONL 会话。"""

        session = self._session
        identity = self._identity
        coord = self._coord
        await coord.flush_background_operations()
        session.session_state.reset(
            uuid.uuid4().hex[:8],
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        await self._capabilities.on_new_session()
        coord._core_compaction_required = False
        coord._last_context_actions = ()
        coord._runtime.harness.clear_queues()
        coord._runtime.harness.replace_messages([])
        coord.reset_core_observers()
        await coord.ensure_core_session_ready()
        coord.reset_session_usage()
        identity._emit_notice("Conversation cleared.")

    async def restore_core_session(self, session_id: str) -> bool:
        """从 JSONL 回放唯一 Core history，并继续追加到同一会话。"""

        session = self._session
        identity = self._identity
        coord = self._coord
        await coord.flush_background_operations()
        state = await session._session_repository.load(session_id)
        if state is None:
            return False
        coord.provider_manager.restore_configuration(
            model=state.model,
            thinking_level=state.thinking_level,
        )
        started_at = session.session_state.started_at
        coord._core_compaction_required = False
        coord._last_context_actions = ()
        coord._runtime.harness.clear_queues()
        coord._runtime.harness.replace_messages(state.messages)
        if state.session_info is not None:
            started_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(state.session_info.created_at),
            )
        session.session_state.reset(session_id, started_at)
        await self._capabilities.on_restore_session()
        coord.reset_core_observers()
        await coord.ensure_core_session_ready()
        coord.reset_session_usage()
        identity._emit_notice(f"Session restored ({len(state.messages)} messages).")
        return True

    async def compact(self) -> None:
        coord = self._coord
        await coord.ensure_core_session_ready()
        if await coord.compact_core_context_if_needed(force=True, reason="manual"):
            self._identity._emit_notice("Conversation compacted.")

    async def close(self) -> None:
        """按既有 finally 链回收后台任务、Core runtime、Provider 与 Capability 资源。"""

        coord = self._coord
        try:
            await coord.flush_background_operations()
        finally:
            try:
                await coord._runtime.aclose()
            finally:
                await self._capabilities.close()
