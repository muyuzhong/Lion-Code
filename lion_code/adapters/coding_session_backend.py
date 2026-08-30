"""FullProfile 产品的 CodingSessionBackend 组合适配器。

目标依赖链::

    LionCodingSession → CodingSessionBackend protocol
        ↑ 结构化实现
    CodingSessionBackendAdapter → 委托 MetaAgent + product controllers

通用 Agent 能力全部来自 MetaAgent；产品职责（session 枚举/legacy 迁移、
Plan 审批、terminal 回调、confirmation、notices、cost 投影）在本适配器
通过组合实现，禁止继承 MetaAgent。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from ..application.ports import EgressConfigurationPort
from ..capabilities.plan.runtime import PlanRuntime
from ..composition.ports import (
    ConfirmationController,
    NoticeController,
    SubagentStatusSink,
)
from ..meta_agent import MetaAgent
from ..permission_state import PermissionMode
from ..runtime.agent import AgentRunResult
from ..runtime.provider import ProviderReadiness
from ..session_runtime import (
    SessionRecorder,
    SessionRepository,
    legacy_session_messages,
    list_legacy_sessions,
    load_legacy_session,
)
from ..usage import UsageSnapshot


class CodingSessionBackendAdapter:
    """通过组合 MetaAgent 与 product controllers 实现 CodingSessionBackend。"""

    def __init__(
        self,
        *,
        agent: MetaAgent,
        plan: PlanRuntime,
        confirmation: ConfirmationController,
        notices: NoticeController,
        status_sink: SubagentStatusSink,
        terminal_output_sink: Callable[[bool], None],
        session_renamer: Callable[[str, str], Awaitable[bool]],
        session_repository: SessionRepository,
        egress_configuration: EgressConfigurationPort,
        cwd: Path,
    ) -> None:
        self._agent = agent
        self._plan = plan
        self._confirmation = confirmation
        self._notices = notices
        self._status_sink = status_sink
        self._terminal_output_sink = terminal_output_sink
        self._session_renamer = session_renamer
        self._session_repository = session_repository
        self._egress_configuration = egress_configuration
        self._cwd = cwd

    # ─── ConversationPort ────────────────────────────────────

    @property
    def messages(self) -> tuple:
        return self._agent.messages

    def subscribe(self, listener: Callable) -> Callable[[], None]:
        return self._agent.subscribe(listener)

    async def prompt(self, content: str) -> None:
        await self._agent.prompt(content)

    async def continue_(self) -> None:
        await self._agent.continue_()

    def steer(self, content: str) -> Any:
        return self._agent.steer(content)

    def follow_up(self, content: str) -> Any:
        return self._agent.follow_up(content)

    def queue_snapshot(self) -> Any:
        return self._agent.queue_snapshot()

    def cancel(self) -> None:
        self._agent.cancel()

    @property
    def cancelled(self) -> bool:
        return self._agent.cancelled

    async def compact_for_overflow(self) -> bool:
        return await self._agent.compact_for_overflow()

    # ─── SessionPort ─────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._agent.session_id

    async def list_sessions(self) -> list[dict[str, Any]]:
        """统一枚举新 JSONL 与尚未迁移的旧 JSON Session。"""
        current = await self._session_repository.list_sessions()
        current_ids = {str(item.get("id")) for item in current}
        legacy = [
            item
            for item in list_legacy_sessions(self._session_repository.session_dir)
            if str(item.get("id")) not in current_ids
        ]
        sessions = [*current, *legacy]
        sessions.sort(key=lambda item: str(item.get("startTime", "")), reverse=True)
        return sessions

    async def resume(self, session_id: str) -> bool:
        """优先恢复 JSONL；遇到旧 JSON 时原地迁移且保留源文件。"""
        if self._session_repository.exists(session_id):
            if await self._agent.restore(session_id):
                return True
        legacy = load_legacy_session(
            self._session_repository.session_dir,
            session_id,
        )
        if legacy is None:
            return False
        await self._migrate_legacy_core_session(session_id, legacy)
        return await self._agent.restore(session_id)

    async def rename_session(self, session_id: str, label: str) -> bool:
        return await self._session_renamer(session_id, label)

    async def restore_latest(self) -> bool:
        sessions = await self.list_sessions()
        if not sessions:
            self._notices.emit("No previous sessions found.")
            return False
        session_id = str(sessions[0]["id"])
        restored = await self.resume(session_id)
        if not restored:
            self._notices.emit(
                f"Session {session_id} could not be restored in this runtime."
            )
        return restored

    async def new_session(self) -> None:
        await self._agent.new_session()

    async def compact(self) -> None:
        await self._agent.compact()

    async def aclose(self) -> None:
        await self._agent.close()

    async def _migrate_legacy_core_session(
        self,
        session_id: str,
        legacy: dict[str, Any],
    ) -> None:
        metadata = legacy.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        recorder = SessionRecorder(
            session_id=session_id,
            model=str(metadata.get("model") or self._agent.model),
            thinking_level=self._agent.thinking_level,
            cwd=Path(str(metadata.get("cwd") or self._cwd)),
            storage=self._session_repository.storage_for(session_id),
        )
        # 迁移是显式保留历史会话：即使没有消息也必须落盘初始元数据，
        # 保证 JSONL 存在且不再重复枚举 legacy 文件（区别于新建会话的惰性落盘）。
        await recorder.ensure_on_disk()
        for message in legacy_session_messages(legacy):
            await recorder.record_message(message)

    # ─── SettingsPort ────────────────────────────────────────

    @property
    def cwd(self) -> Path:
        return self._cwd

    @property
    def model(self) -> str:
        return self._agent.model

    @property
    def provider_name(self) -> str:
        return self._agent.provider_name

    @property
    def provider_readiness(self) -> ProviderReadiness:
        return self._agent.provider_readiness

    @property
    def permission_mode(self) -> PermissionMode:
        return self._agent.permission_mode

    @property
    def api_configured(self) -> bool:
        return self.provider_readiness.ready

    def provider_config(self) -> dict[str, Any]:
        return self._agent.provider_config()

    def configure_provider(self, **kwargs: Any) -> None:
        self._agent.configure_provider(**kwargs)

    def egress_hosts(self) -> list[str]:
        return self._egress_configuration.egress_hosts()

    def configure_egress(self, allow_hosts: Sequence[str]) -> list[str]:
        return self._egress_configuration.configure_egress(allow_hosts)

    @property
    def thinking_level(self) -> str:
        return str(self._agent.thinking_level)

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        return tuple(str(level) for level in self._agent.available_thinking_levels)

    def set_thinking_level(self, level: str) -> str:
        return str(self._agent.set_thinking_level(level))

    def cycle_thinking_level(self) -> str:
        return str(self._agent.cycle_thinking_level())

    def set_terminal_output(self, enabled: bool) -> None:
        self._terminal_output_sink(enabled)
        self._confirmation.terminal_output = enabled
        self._status_sink.terminal_output = enabled

    # ─── UsagePort ───────────────────────────────────────────

    def token_usage(self) -> UsageSnapshot:
        return self._agent.usage

    # ─── ControlPort ─────────────────────────────────────────

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self._confirmation.confirm_fn = fn

    def set_plan_approval_fn(
        self, fn: Callable[[str], Awaitable[dict[str, Any]]] | None
    ) -> None:
        self._plan.set_approval_fn(fn)

    def set_notice_fn(
        self,
        fn: Callable[[str, Literal["info", "error"]], None] | None,
    ) -> None:
        self._notices.set_notice_fn(fn)

    def toggle_plan_mode(self) -> str:
        return self._plan.toggle()

    # ─── REPL / one-shot 产品便利 API ────────────────────────

    async def chat(self, prompt: str) -> None:
        await self._agent.chat(prompt)

    async def run(self, prompt: str, *, timeout: float | None = None) -> AgentRunResult:
        return await self._agent.run(prompt, timeout=timeout)

    def abort(self) -> None:
        self._agent.cancel()

    @property
    def is_aborted(self) -> bool:
        return self._agent.cancelled

    @property
    def is_processing(self) -> bool:
        return self._agent.is_running

    async def clear_history(self) -> None:
        await self.new_session()

    async def close(self) -> None:
        await self.aclose()

    def show_cost(self) -> None:
        """cost/usage 产品投影：格式化用量并经 notice 通道输出。"""
        usage = self._agent.usage
        budget = self._agent.budget
        max_cost = budget.max_cost_usd
        max_turns = budget.max_turns
        budget_info = f" / ${max_cost} budget" if max_cost else ""
        turn_info = f" | Turns: {usage.turns}/{max_turns}" if max_turns else ""
        cached = usage.cache_read_tokens
        billed_input = usage.input_tokens + usage.cache_write_tokens + cached
        hit_rate = round((cached / billed_input) * 100) if billed_input > 0 else 0
        cache_info = (
            f"\n  Cache: {cached} read / {usage.cache_write_tokens} write ({hit_rate}% of input from cache)"
            if (cached or usage.cache_write_tokens)
            else ""
        )
        self._notices.emit(
            f"Tokens: {usage.input_tokens} in / {usage.output_tokens} out{cache_info}\n  Estimated cost: ${usage.cost_usd:.4f}{budget_info}{turn_info}"
        )


__all__ = ["CodingSessionBackendAdapter"]
