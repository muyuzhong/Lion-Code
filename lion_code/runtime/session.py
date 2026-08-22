"""会话运行时：SessionIdentity / SessionRepository / SessionRecorder 生命周期的唯一 Owner。

SessionRuntime 不感知 ProviderController 与 AgentRuntime。Provider 配置变更经
``record_configuration_change`` 窄端口进入；恢复会话时只产出不可变
``SessionRestoreState``，跨 Owner 编排（restore_configuration + 回放）由上层 facade 完成。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.messages import AgentMessage
from ..session_runtime import SessionRecorder, SessionRepository
from .session_identity import SessionIdentityState

if TYPE_CHECKING:
    from ..capabilities import CapabilityLifecycle
    from .provider import ProviderView


@dataclass(frozen=True, slots=True)
class SessionRestoreState:
    """``SessionRuntime.load`` 产出的不可变恢复快照。"""

    session_id: str
    started_at: str
    messages: tuple[AgentMessage, ...]
    model: str | None
    thinking_level: str | None


class SessionRuntime:
    """拥有会话身份、JSONL 仓库与 Recorder 生命周期。"""

    def __init__(
        self,
        *,
        session_state: SessionIdentityState,
        repository: SessionRepository,
        capabilities: CapabilityLifecycle,
        is_sub_agent: bool,
        cwd: Path,
        initial_model: str,
        initial_thinking_level: str,
    ) -> None:
        self._session_state = session_state
        self._repository = repository
        self._capabilities = capabilities
        self._is_sub_agent = is_sub_agent
        self._cwd = cwd
        self._recorder: SessionRecorder | None = None
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._background_errors: list[BaseException] = []
        self._reset_recorder(
            model=initial_model,
            thinking_level=initial_thinking_level,
        )

    @property
    def state(self) -> SessionIdentityState:
        return self._session_state

    @property
    def repository(self) -> SessionRepository:
        return self._repository

    @property
    def recorder(self) -> SessionRecorder | None:
        return self._recorder

    # ─── 会话生命周期 ─────────────────────────────────────────

    async def new_session(
        self,
        *,
        model: str,
        thinking_level: str | None,
    ) -> None:
        """结束当前会话身份并开启新 Session；旧 JSONL 保持 append-only 可恢复。"""

        await self.flush()
        self._session_state.reset(
            uuid.uuid4().hex[:8],
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._reset_recorder(model=model, thinking_level=thinking_level)
        await self._capabilities.on_new_session()

    async def load(self, session_id: str) -> SessionRestoreState | None:
        """收敛待写 Entry 后读取会话，返回不可变恢复快照。"""

        await self.flush()
        state = await self._repository.load(session_id)
        if state is None:
            return None
        started_at = self._session_state.started_at
        if state.session_info is not None:
            started_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(state.session_info.created_at),
            )
        return SessionRestoreState(
            session_id=session_id,
            started_at=started_at,
            messages=state.messages,
            model=state.model,
            thinking_level=state.thinking_level,
        )

    async def restore(
        self,
        state: SessionRestoreState,
        *,
        model: str,
    ) -> None:
        """把身份切换到恢复的会话并重建 Recorder；消息回放由 ConversationRuntime 承担。"""

        self._session_state.reset(state.session_id, state.started_at)
        self._reset_recorder(model=model, thinking_level=state.thinking_level)
        await self._capabilities.on_restore_session()

    async def ensure_ready(self) -> None:
        """收敛待写 Entry 并完成 Recorder 写入位置恢复。"""
        await self.flush()
        if self._recorder is not None:
            await self._recorder.initialize()

    async def close(self) -> None:
        """收敛待写 Entry 并关闭 Capability 会话参与者。"""
        try:
            await self.flush()
        finally:
            await self._capabilities.close()

    # ─── 压缩 / 分支 Entry 记录（AgentRuntime 编排调用）────────

    async def record_compaction(
        self,
        *,
        summary: str,
        replaces_entry_ids: list[str],
    ) -> None:
        if self._recorder is None:
            raise RuntimeError("No session recorder for compaction")
        await self._recorder.record_compaction(
            summary=summary,
            replaces_entry_ids=replaces_entry_ids,
        )

    async def record_branch_summary(
        self,
        *,
        summary: str,
        branch_root_id: str | None,
    ) -> None:
        """把旧 Session 的九段摘要写入当前（新建）Session 首条 Entry。"""
        if self._recorder is None:
            raise RuntimeError("No session recorder for branch summary")
        await self._recorder.record_branch_summary(
            summary=summary,
            branch_root_id=branch_root_id,
        )

    async def context_entry_ids(self) -> tuple[str, ...]:
        if self._recorder is None:
            raise RuntimeError("No session recorder for context entries")
        return await self._recorder.context_entry_ids()

    # ─── ProviderController 配置记录窄端口 ────────────────────

    def record_configuration_change(
        self,
        previous: ProviderView,
        current: ProviderView,
    ) -> None:
        """把 Provider 配置变化异步落到当前 Session（同步命令入口）。"""

        recorder = self._recorder
        if recorder is None:
            return
        model_changed = previous.model != current.model
        thinking_level_changed = previous.thinking_level != current.thinking_level
        thinking_mode_changed = previous.thinking_mode != current.thinking_mode
        if not (model_changed or thinking_level_changed or thinking_mode_changed):
            return

        async def persist_configuration() -> object:
            if model_changed:
                await recorder.record_model_change(current.model)
            if thinking_level_changed:
                await recorder.record_thinking_level_change(current.thinking_level)
            elif thinking_mode_changed:
                await recorder.record_thinking_level_change(current.thinking_mode)
            return None

        self._schedule_background_operation(persist_configuration)

    # ─── 内部 ─────────────────────────────────────────────────

    def _reset_recorder(self, *, model: str, thinking_level: str | None) -> None:
        """按当前会话身份重建 Recorder；sub-agent 不落盘会话。"""
        if self._is_sub_agent:
            self._recorder = None
            return
        self._recorder = SessionRecorder(
            session_id=self._session_state.id,
            model=model,
            thinking_level=thinking_level,
            cwd=self._cwd,
            storage=self._repository.storage_for(self._session_state.id),
        )

    def _schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(operation())
            return
        task: asyncio.Task[object] = loop.create_task(operation())
        self._background_tasks.add(task)

        def collect_result(done: asyncio.Task[object]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except BaseException as error:
                self._background_errors.append(error)

        task.add_done_callback(collect_result)

    async def flush(self) -> None:
        """收敛已排程的配置 Entry 写入任务，重放第一个异常。"""
        pending = tuple(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._background_errors:
            raise self._background_errors.pop(0)
