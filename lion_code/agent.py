"""Agent 核心循环：统一 Anthropic 与 OpenAI 兼容后端的流式调用、上下文压缩、
Plan 模式、子 Agent、权限与预算控制。整体分层参考 Claude Code 的公开设计。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any, Literal

from .composition import (
    AgentConfig,
    FullProfile,
    InteractionBindings,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
    ToolBindings,
    build_agent_composition,
)
from .context import (
    ContextCompactor,
    ContextManager,
    ModelLimitsResolver,
)
from .core.conversation import QueueSnapshot
from .core.provider import ModelProvider
from .hooks import load_pre_tool_use_hooks
from .meta_agent import MetaAgent
from .observers import TerminalRenderer
from .permission_state import (
    PermissionMode,
)
from .prompt import (
    build_dynamic_system_context,
)
from .providers.factory import create_provider
from .runtime.agent import AgentRunResult as AgentRunResult
from .runtime.agent import LionAgentRuntime
from .runtime.session_identity import SessionIdentityState
from .session_runtime import (
    SessionRecorder,
    SessionRepository,
    legacy_session_messages,
    list_legacy_sessions,
    load_legacy_session,
)
from .tooling import ToolRegistry
from .ui import (
    print_confirmation,
    print_error,
    print_info,
    print_sub_agent_end,
    print_sub_agent_start,
)
from .usage import UsageSnapshot


def _agent_provider_factory(**kwargs: Any) -> ModelProvider:
    """保留 ``lion_code.agent.create_provider`` 的动态 monkeypatch seam。"""

    return create_provider(**kwargs)


def _agent_hooks_loader() -> list[Any]:
    return load_pre_tool_use_hooks()


def _agent_dynamic_context_builder(names: Sequence[str]) -> str:
    return build_dynamic_system_context(list(names))


def _agent_terminal_renderer_factory() -> TerminalRenderer:
    return TerminalRenderer()


def _agent_print_info(message: str) -> None:
    print_info(message)


def _agent_print_error(message: str) -> None:
    print_error(message)


def _agent_print_confirmation(message: str) -> None:
    print_confirmation(message)


def _agent_print_subagent_start(agent_type: str, description: str) -> None:
    print_sub_agent_start(agent_type, description)


def _agent_print_subagent_end(agent_type: str, description: str) -> None:
    print_sub_agent_end(agent_type, description)


# ─── Agent ──────────────────────────────────────────────────


class Agent(MetaAgent):
    """供 CLI/Application 使用的 FullProfile backend adapter。"""

    def __init__(
        self,
        *,
        permission_mode: PermissionMode = "default",
        model: str = "claude-opus-4-6",
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        api_key: str | None = None,
        thinking: bool = False,
        max_cost_usd: float | None = None,
        max_turns: int | None = None,
        confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
        custom_system_prompt: str | None = None,
        tool_registry: ToolRegistry | None = None,
        session_repository: SessionRepository | None = None,
        context_manager: ContextManager | None = None,
        context_compactor: ContextCompactor | None = None,
        model_limits_resolver: ModelLimitsResolver | None = None,
        is_sub_agent: bool = False,
        terminal_output: bool = True,
        config: AgentConfig | None = None,
        bindings: RuntimeBindings | None = None,
    ) -> None:
        legacy_config = AgentConfig(
            permission_mode=permission_mode,
            model=model,
            api_base=api_base,
            anthropic_base_url=anthropic_base_url,
            api_key=api_key,
            thinking=thinking,
            max_cost_usd=max_cost_usd,
            max_turns=max_turns,
            is_sub_agent=is_sub_agent,
            terminal_output=terminal_output,
        )
        if config is not None:
            if legacy_config != AgentConfig() or custom_system_prompt is not None:
                raise ValueError(
                    "config cannot be combined with legacy configuration arguments"
                )
            resolved_config = config
        else:
            resolved_config = legacy_config

        legacy_bindings_supplied = any(
            value is not None
            for value in (
                confirm_fn,
                tool_registry,
                session_repository,
                context_manager,
                context_compactor,
                model_limits_resolver,
            )
        )
        if bindings is not None and legacy_bindings_supplied:
            raise ValueError(
                "bindings cannot be combined with legacy dependency arguments"
            )
        resolved_bindings = bindings or RuntimeBindings(
            provider=ProviderBindings(
                provider_factory=_agent_provider_factory,
                model_limits_resolver=model_limits_resolver,
            ),
            session=SessionBindings(
                session_repository=session_repository,
                context_manager=context_manager,
                context_compactor=context_compactor,
            ),
            tool=ToolBindings(
                tool_registry=tool_registry,
                pre_tool_use_hooks_loader=_agent_hooks_loader,
            ),
            interaction=InteractionBindings(
                confirm_fn=confirm_fn,
                dynamic_system_context_builder=_agent_dynamic_context_builder,
                terminal_renderer_factory=_agent_terminal_renderer_factory,
                print_info=_agent_print_info,
                print_error=_agent_print_error,
                print_confirmation=_agent_print_confirmation,
                print_sub_agent_start=_agent_print_subagent_start,
                print_sub_agent_end=_agent_print_subagent_end,
            ),
        )
        # Agent 是 Full Product：prompt/tools 等组合选择只经由 FullProfile 进入
        # Composition Root，facade 不再拼接 capability 集合。
        profile = FullProfile(system_prompt=custom_system_prompt)
        composition = build_agent_composition(
            profile,
            config=resolved_config,
            bindings=resolved_bindings,
        )
        # Agent 是 Full Product：显式选择全部内置能力，Feature 字段必然存在。
        assert composition.plan is not None
        assert composition.subagent_factory is not None
        assert composition.subagent_executor is not None
        assert composition.skill_runtime is not None
        assert composition.status_sink is not None

        super().__init__(
            runtime=composition.runtime_coordinator,
            provider_manager=composition.provider_manager,
            session_state=composition.session_state,
            usage=composition.usage,
            budget=composition.budget,
            permission_mode=resolved_config.permission_mode,
        )

        self.is_sub_agent = resolved_config.is_sub_agent
        self._current_task: asyncio.Task | None = None
        self._notice_controller = composition.notices
        self._confirmation = composition.confirmation
        self._status_sink = composition.status_sink
        self._session_state = composition.session_state
        self._session_repository = composition.session_repository
        self._usage = composition.usage
        self._budget = composition.budget
        self.plan = composition.plan
        self.tool_registry = composition.tool_registry
        self._subagent_factory = composition.subagent_factory
        self._subagent_executor = composition.subagent_executor
        self._capability_registry = composition.capability_registry
        self._capability_runtime = composition.capability_runtime
        self._prompt_composer = composition.prompt_composer
        self.tool_context = composition.tool_context
        self.tool_runtime = composition.tool_runtime
        self._provider_manager = composition.provider_manager
        self._runtime_coordinator = composition.runtime_coordinator
        self.confirm_fn = resolved_bindings.interaction.confirm_fn

    @property
    def _core_runtime(self) -> LionAgentRuntime:
        """兼容暴露唯一 Core Runtime；实际所有权在运行时协调器。"""

        return self._runtime_coordinator.core_runtime

    @_core_runtime.setter
    def _core_runtime(self, value: LionAgentRuntime) -> None:
        self._runtime_coordinator.core_runtime = value

    @property
    def _session_recorder(self) -> SessionRecorder | None:
        return self._runtime_coordinator.session_recorder

    @_session_recorder.setter
    def _session_recorder(self, value: SessionRecorder | None) -> None:
        self._runtime_coordinator.session_recorder = value

    @property
    def _context_compactor(self) -> ContextCompactor | None:
        return self._runtime_coordinator.context_compactor

    @_context_compactor.setter
    def _context_compactor(self, value: ContextCompactor | None) -> None:
        self._runtime_coordinator.context_compactor = value

    @property
    def _context_manager(self) -> ContextManager:
        return self._runtime_coordinator.context_manager

    @property
    def _resolved_model_limits_for(self) -> tuple[int, str] | None:
        return self._runtime_coordinator.resolved_model_limits_for

    @_resolved_model_limits_for.setter
    def _resolved_model_limits_for(self, value: tuple[int, str] | None) -> None:
        self._runtime_coordinator.resolved_model_limits_for = value

    @property
    def _core_compaction_required(self) -> bool:
        return self._runtime_coordinator.core_compaction_required

    @_core_compaction_required.setter
    def _core_compaction_required(self, value: bool) -> None:
        self._runtime_coordinator.core_compaction_required = value

    @property
    def _terminal_renderer(self) -> TerminalRenderer | None:
        return self._runtime_coordinator.terminal_renderer

    @property
    def effective_window(self) -> int:
        return self._runtime_coordinator._identity.effective_window

    @effective_window.setter
    def effective_window(self, value: int) -> None:
        self._runtime_coordinator._identity.effective_window = value

    @property
    def _last_stop_reason(self) -> str | None:
        return self._runtime_coordinator._identity._last_stop_reason

    @_last_stop_reason.setter
    def _last_stop_reason(self, value: str | None) -> None:
        self._runtime_coordinator._identity._last_stop_reason = value

    @property
    def confirm_fn(self) -> Callable[[str], Awaitable[bool]] | None:
        return self._confirmation.confirm_fn

    @confirm_fn.setter
    def confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self._confirmation.confirm_fn = fn

    @property
    def is_processing(self) -> bool:
        return self._core_runtime.harness.is_running

    @property
    def session_state(self) -> SessionIdentityState:
        return self._session_state

    @property
    def is_aborted(self) -> bool:
        """最近一次运行是否已收到取消请求。"""

        return self._runtime_coordinator.execution.cancelled

    @property
    def core_runtime(self) -> LionAgentRuntime:
        """返回供应用会话层订阅事件与读取消息快照的 Core Runtime。"""
        return self._core_runtime

    def abort(self) -> None:
        self._runtime_coordinator.abort()

    # 应用层只通过这些语义方法访问会话，不接触 Core Runtime 的所有权细节。

    @property
    def cwd(self) -> Path:
        return Path(self.tool_context.cwd)

    @property
    def provider_name(self) -> str:
        return self._provider_manager.view.provider_kind

    def queue_snapshot(self) -> QueueSnapshot:
        return self._core_runtime.queue_snapshot()

    async def compact_for_overflow(self) -> bool:
        return await self.compact_core_context_for_overflow()

    async def aclose(self) -> None:
        await self.close()

    async def resume(self, session_id: str) -> bool:
        return await self.restore_session_id(session_id)

    async def restore(self, session_id: str) -> bool:
        return await self.restore_session_id(session_id)

    async def restore_latest(self) -> bool:
        return await self.restore_latest_session()

    def token_usage(self) -> UsageSnapshot:
        return self._usage.snapshot()

    # ─── Core Runtime ────────────────────────────────────────

    async def _ensure_core_session_ready(self) -> None:
        await self._runtime_coordinator.ensure_core_session_ready()

    async def compact_core_context_for_overflow(self) -> bool:
        return await self._runtime_coordinator.compact_core_context_for_overflow()

    def _schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        self._runtime_coordinator.schedule_background_operation(operation)

    def set_terminal_output(self, enabled: bool) -> None:
        self._runtime_coordinator.set_terminal_output(enabled)
        self._confirmation.terminal_output = enabled
        self._status_sink.terminal_output = enabled

    def set_notice_fn(
        self,
        fn: Callable[[str, Literal["info", "error"]], None] | None,
    ) -> None:
        """设置实例级状态通知回调；未设置时继续直接输出到终端。"""

        self._notice_controller.set_notice_fn(fn)

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        self._notice_controller.emit(message, role=role)

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self.confirm_fn = fn

    def set_plan_approval_fn(self, fn: Callable[[str], Awaitable[dict]] | None) -> None:
        self.plan.set_approval_fn(fn)

    # ─── Plan 模式切换 ───────────────────────────────────────

    def toggle_plan_mode(self) -> str:
        return self.plan.toggle()

    # ─── 运行时模型/凭证配置（TUI /model 的后端）──────────────

    @property
    def api_configured(self) -> bool:
        return self._provider_manager.api_configured

    # ─── REPL 命令状态 ───────────────────────────────────────

    async def clear_history(self) -> None:
        """结束当前会话并创建新 Session；旧 append-only 历史保持可恢复。"""
        await self._runtime_coordinator.clear_history()

    def show_cost(self) -> None:
        usage = self._usage.snapshot()
        max_cost = self._budget.max_cost_usd
        max_turns = self._budget.max_turns
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
        self._emit_notice(
            f"Tokens: {usage.input_tokens} in / {usage.output_tokens} out{cache_info}\n  Estimated cost: ${usage.cost_usd:.4f}{budget_info}{turn_info}"
        )

    # ─── 会话持久化 ──────────────────────────────────────────

    async def restore_core_session(self, session_id: str) -> bool:
        """从 JSONL 重建 Harness 唯一历史，并继续追加同一 Session。"""
        return await self._runtime_coordinator.restore_core_session(session_id)

    async def restore_session_id(self, session_id: str) -> bool:
        """优先恢复 JSONL；Core 遇到旧 JSON 时原地迁移且保留源文件。"""
        if self._session_repository.exists(session_id):
            restored = await self.restore_core_session(session_id)
            if restored:
                return True
        legacy = load_legacy_session(
            self._session_repository.session_dir,
            session_id,
        )
        if legacy is None:
            return False
        await self._migrate_legacy_core_session(session_id, legacy)
        return await self.restore_core_session(session_id)

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

    async def latest_session_id(self) -> str | None:
        sessions = await self.list_sessions()
        return str(sessions[0]["id"]) if sessions else None

    async def restore_latest_session(self) -> bool:
        session_id = await self.latest_session_id()
        if session_id is None:
            self._emit_notice("No previous sessions found.")
            return False
        restored = await self.restore_session_id(session_id)
        if not restored:
            self._emit_notice(
                f"Session {session_id} could not be restored in this runtime."
            )
        return restored

    async def _migrate_legacy_core_session(
        self,
        session_id: str,
        legacy: dict[str, Any],
    ) -> None:
        metadata = legacy.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        recorder = SessionRecorder(
            session_id=session_id,
            model=str(metadata.get("model") or self.model),
            thinking_level=self.thinking_level,
            cwd=Path(str(metadata.get("cwd") or self.tool_context.cwd)),
            storage=self._session_repository.storage_for(session_id),
        )
        await recorder.initialize()
        for message in legacy_session_messages(legacy):
            await recorder.record_message(message)

    # ─── 工具执行 ────────────────────────────────────────────

    async def _execute_tool_call(
        self,
        name: str,
        inp: dict,
        tool_call_id: str = "",
    ) -> str:
        # 保留旧测试与嵌入方替换 Agent 确认方法的 seam；正式 Core 路径使用
        # Composition Root 注入的 ConfirmationController。
        self.tool_context.confirm_fn = self._confirm_dangerous
        self.tool_context.confirm_hook_trust = self._confirm_hook_trust
        result = await self.tool_runtime.execute(
            tool_call_id=tool_call_id,
            name=name,
            arguments=inp,
        )
        return result.content

    async def _confirm_hook_trust(self, message: str) -> bool:
        # 项目 Hook 信任独立于工具权限；--yolo 也不能替仓库代码自动取得信任。
        if self.permission_mode == "dontAsk":
            return False
        return await self._confirm_dangerous(message)

    async def _confirm_dangerous(self, command: str) -> bool:
        return await self._confirmation.confirm(command)
