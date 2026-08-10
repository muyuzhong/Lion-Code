"""会话生命周期协调：clear/restore/compact/close。

从 ``AgentRuntimeCoordinator`` 拆出，收敛 JSONL 会话的创建、恢复、压缩与关闭。
不复制 coordinator 的 ``reset_core_observers`` / ``reset_session_usage``
逻辑，而是通过持有 coordinator 引用调用。
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from lion_code.context import effective_window_tokens, fallback_model_limits
from lion_code.memory_runtime import MemoryInjectionReport
from lion_code.providers.thinking import coerce_thinking_level

if TYPE_CHECKING:
    from lion_code.agent_runtime import (
        AgentRuntimeCoordinator,
        LionAgentRuntime,
        MemoryTurnHost,
        RuntimeIdentityHost,
        SessionStateHost,
    )


class SessionLifecycle:
    """拥有 clear/restore/compact/close 的会话生命周期协调。"""

    def __init__(self, coordinator: AgentRuntimeCoordinator) -> None:
        self._coord = coordinator

    @property
    def _identity(self) -> RuntimeIdentityHost:
        return self._coord._identity

    @property
    def _session(self) -> SessionStateHost:
        return self._coord._session

    @property
    def _memory(self) -> MemoryTurnHost:
        return self._coord._memory

    @property
    def _runtime(self) -> LionAgentRuntime:
        return self._coord._runtime

    async def clear_history(self) -> None:
        """创建新的 JSONL 会话，同时保留项目级 Session Memory。"""

        session = self._session
        memory = self._memory
        identity = self._identity
        coord = self._coord
        await coord.flush_background_operations()
        memory._memory_coordinator.reset()
        memory._reload_project_memory()
        memory._reload_session_memory()
        memory._last_memory_injection = MemoryInjectionReport()
        session.session_state.reset(
            uuid.uuid4().hex[:8],
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        session.plan.reset_for_new_session()
        coord._core_compaction_required = False
        coord._last_context_actions = ()
        coord._runtime.harness.clear_queues()
        coord._runtime.harness.replace_messages([])
        coord.reset_core_observers()
        await coord.ensure_core_session_ready()
        coord.reset_session_usage()
        memory._turn_memory_overlays = memory._build_turn_memory_overlays()
        identity._emit_notice("Conversation cleared.")

    async def restore_core_session(self, session_id: str) -> bool:
        """从 JSONL 回放唯一 Core history，并继续追加到同一会话。"""

        session = self._session
        memory = self._memory
        identity = self._identity
        coord = self._coord
        await coord.flush_background_operations()
        state = await session._session_repository.load(session_id)
        if state is None:
            return False
        memory._memory_coordinator.reset()
        memory._reload_project_memory()
        memory._reload_session_memory()
        memory._last_memory_injection = MemoryInjectionReport()
        started_at = session.session_state.started_at
        session.plan.reset_after_restore()
        coord._core_compaction_required = False
        coord._last_context_actions = ()
        coord._runtime.harness.clear_queues()
        coord._runtime.harness.replace_messages(state.messages)
        if state.model is not None:
            identity.model = state.model
            identity.effective_window = effective_window_tokens(
                fallback_model_limits(identity.model)
            )
            coord._resolved_model_limits_for = None
            coord._runtime.set_model(identity.model)
        if state.thinking_level is not None:
            restored_level = coerce_thinking_level(state.thinking_level)
            if restored_level != identity._thinking_level:
                identity._apply_core_thinking_level(restored_level)
        if state.session_info is not None:
            started_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(state.session_info.created_at),
            )
        session.session_state.reset(session_id, started_at)
        coord.reset_core_observers()
        await coord.ensure_core_session_ready()
        coord.reset_session_usage()
        memory._turn_memory_overlays = memory._build_turn_memory_overlays()
        identity._emit_notice(f"Session restored ({len(state.messages)} messages).")
        return True

    async def compact(self) -> None:
        coord = self._coord
        await coord.ensure_core_session_ready()
        if await coord.compact_core_context_if_needed(force=True):
            self._identity._emit_notice("Conversation compacted.")

    async def close(self) -> None:
        """按既有 finally 链回收后台、Memory、Provider 与 MCP 环境。"""

        coord = self._coord
        try:
            await coord.flush_background_operations()
        finally:
            try:
                await self._memory._memory_coordinator.close()
            finally:
                try:
                    await coord._runtime.aclose()
                finally:
                    await self._session.tool_environment.close()
