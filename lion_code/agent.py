"""Agent 核心循环：统一 Anthropic 与 OpenAI 兼容后端的流式调用、上下文压缩、
Plan 模式、子 Agent、权限与预算控制。整体分层参考 Claude Code 的公开设计。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from .agent_runtime import (
    AgentRunResult,
    LionAgentRuntime,
)
from .composition import AgentConfig, AgentDependencies, build_agent_composition
from .context import (
    ContextCompactor,
    ContextManager,
    ModelLimitsResolver,
)
from .core.conversation import QueueSnapshot
from .core.harness import EventListener
from .core.messages import AgentMessage
from .core.provider import ModelProvider
from .hooks import load_pre_tool_use_hooks
from .learning_runtime import (
    LEARN_META_SKILL_PROMPT,  # noqa: F401
)
from .memory_runtime import (
    MemoryContextInjector,
    MemoryCoordinator,
    MemoryInjectionReport,
    MemoryOverlay,
)
from .observers import TerminalRenderer
from .permission_state import (
    PermissionMode,
)
from .project_identity import ProjectIdentity, resolve_project_identity
from .prompt import (
    build_dynamic_system_context,
    load_project_context_files,
)
from .providers.factory import create_provider
from .providers.thinking import (
    ThinkingLevel,
)
from .session_identity import SessionIdentityState
from .session_memory import (
    SessionMemory,
    SessionMemoryRepository,
)
from .session_runtime import (
    SessionRecorder,
    SessionRepository,
    legacy_session_messages,
    list_legacy_sessions,
    load_legacy_session,
)
from .subagent_factory import ChildAgentConfig
from .tooling import ToolEnvironment, ToolRegistry
from .tooling.types import JSONValue
from .tools import ToolDef
from .ui import (
    print_confirmation,
    print_error,
    print_info,
    print_sub_agent_end,
    print_sub_agent_start,
)
from .usage import UsageSnapshot

_ORIGINAL_AGENT_SEMANTIC_EXTRACTOR: object | None = None


def _agent_provider_factory(**kwargs: Any) -> ModelProvider:
    """保留 ``lion_code.agent.create_provider`` 的动态 monkeypatch seam。"""

    return create_provider(**kwargs)


def _agent_hooks_loader() -> list[Any]:
    return load_pre_tool_use_hooks()


def _agent_project_identity_resolver(cwd: Path | None) -> ProjectIdentity:
    return resolve_project_identity(cwd)


def _agent_project_context_loader(
    cwd: Path,
    identity: ProjectIdentity,
) -> Sequence[Any]:
    return load_project_context_files(cwd=cwd, identity=identity)


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


class Agent:
    """协调模型调用、工具执行和会话状态的主运行时对象。"""

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name != "_emit_notice":
            return
        notices = self.__dict__.get("_notice_controller")
        if notices is None:
            return
        if getattr(value, "__self__", None) is self:
            notices.set_notice_fn(None)
        else:
            notices.set_notice_fn(value)

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
        custom_tools: list[ToolDef] | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_environment: ToolEnvironment | None = None,
        session_repository: SessionRepository | None = None,
        session_memory_repository: SessionMemoryRepository | None = None,
        context_manager: ContextManager | None = None,
        context_compactor: ContextCompactor | None = None,
        model_limits_resolver: ModelLimitsResolver | None = None,
        is_sub_agent: bool = False,
        terminal_output: bool = True,
        mcp_enabled: bool = True,
        config: AgentConfig | None = None,
        dependencies: AgentDependencies | None = None,
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
            custom_system_prompt=custom_system_prompt,
            custom_tools=tuple(custom_tools) if custom_tools is not None else None,
            is_sub_agent=is_sub_agent,
            terminal_output=terminal_output,
            mcp_enabled=mcp_enabled,
        )
        if config is not None:
            if legacy_config != AgentConfig():
                raise ValueError(
                    "config cannot be combined with legacy configuration arguments"
                )
            resolved_config = config
        else:
            resolved_config = legacy_config

        legacy_dependencies_supplied = any(
            value is not None
            for value in (
                confirm_fn,
                tool_registry,
                tool_environment,
                session_repository,
                session_memory_repository,
                context_manager,
                context_compactor,
                model_limits_resolver,
            )
        )
        if dependencies is not None and legacy_dependencies_supplied:
            raise ValueError(
                "dependencies cannot be combined with legacy dependency arguments"
            )
        resolved_dependencies = dependencies or AgentDependencies(
            confirm_fn=confirm_fn,
            tool_registry=tool_registry,
            tool_environment=tool_environment,
            session_repository=session_repository,
            session_memory_repository=session_memory_repository,
            context_manager=context_manager,
            context_compactor=context_compactor,
            model_limits_resolver=model_limits_resolver,
            provider_factory=_agent_provider_factory,
            pre_tool_use_hooks_loader=_agent_hooks_loader,
            project_identity_resolver=_agent_project_identity_resolver,
            project_context_loader=_agent_project_context_loader,
            dynamic_system_context_builder=_agent_dynamic_context_builder,
            terminal_renderer_factory=_agent_terminal_renderer_factory,
            print_info=_agent_print_info,
            print_error=_agent_print_error,
            print_confirmation=_agent_print_confirmation,
            print_sub_agent_start=_agent_print_subagent_start,
            print_sub_agent_end=_agent_print_subagent_end,
        )
        composition = build_agent_composition(
            resolved_config,
            resolved_dependencies,
        )

        self.is_sub_agent = resolved_config.is_sub_agent
        self._mcp_enabled = resolved_config.mcp_enabled
        self._current_task: asyncio.Task | None = None
        self._identity_port = composition.identity_port
        self._session_port = composition.session_port
        self._notice_controller = composition.notices
        self._confirmation = composition.confirmation
        self._status_sink = composition.status_sink
        self._mcp_state = composition.mcp_state
        self._permission_controller = composition.permission_controller
        self._session_state = composition.session_state
        self._session_repository = composition.session_repository
        self._usage = composition.usage
        self._budget = composition.budget
        self._read_file_state = composition.read_file_state
        self._pre_tool_use_hooks = composition.pre_tool_use_hooks
        self.tool_environment = composition.tool_environment
        self._mcp_manager = composition.mcp_manager
        self.plan = composition.plan
        self.tool_registry = composition.tool_registry
        self._subagent_factory = composition.subagent_factory
        self._subagent_executor = composition.subagent_executor
        self._skill_runtime = composition.skill_runtime
        self._capability_registry = composition.capability_registry
        self._mcp_capability = composition.mcp_capability
        self._capability_runtime = composition.capability_runtime
        self._refresh_dynamic_context_enabled = (
            composition.refresh_dynamic_context_enabled
        )
        self._prompt_composer = composition.prompt_composer
        self.tool_context = composition.tool_context
        self._permission_policy = composition.permission_policy
        self._result_store = composition.result_store
        self.tool_runtime = composition.tool_runtime
        self._provider_manager = composition.provider_manager
        self._runtime_coordinator = composition.runtime_coordinator
        self._session_memory_coord = composition.session_memory_coordinator
        self._autonomy = composition.autonomy
        self._learning = composition.learning
        self._model_query = composition.model_query
        self.confirm_fn = resolved_dependencies.confirm_fn

    def _resolve_thinking_mode(self) -> str:
        return self._provider_manager.view.thinking_mode

    @property
    def model(self) -> str:
        """当前模型的只读 ProviderView 投影。"""

        return self._provider_manager.view.model

    @property
    def thinking(self) -> bool:
        """兼容布尔 Thinking API 的只读投影。"""

        return self._provider_manager.view.thinking_enabled

    @property
    def use_openai(self) -> bool:
        """兼容旧 API 的 Provider kind 投影。"""

        return self._provider_manager.view.provider_kind == "openai-compatible"

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
    def _terminal_output(self) -> bool:
        return self._identity_port._terminal_output

    @_terminal_output.setter
    def _terminal_output(self, enabled: bool) -> None:
        self._identity_port._terminal_output = enabled
        self._confirmation.terminal_output = enabled
        self._status_sink.terminal_output = enabled

    @property
    def _mcp_initialized(self) -> bool:
        return self._mcp_state.initialized

    @_mcp_initialized.setter
    def _mcp_initialized(self, value: bool) -> None:
        self._mcp_state.initialized = value

    @property
    def effective_window(self) -> int:
        return self._identity_port.effective_window

    @effective_window.setter
    def effective_window(self, value: int) -> None:
        self._identity_port.effective_window = value

    @property
    def _last_stop_reason(self) -> str | None:
        return self._identity_port._last_stop_reason

    @_last_stop_reason.setter
    def _last_stop_reason(self, value: str | None) -> None:
        self._identity_port._last_stop_reason = value

    @property
    def confirm_fn(self) -> Callable[[str], Awaitable[bool]] | None:
        return self._confirmation.confirm_fn

    @confirm_fn.setter
    def confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self._confirmation.confirm_fn = fn

    def _create_terminal_renderer(self) -> TerminalRenderer:
        """在调用时读取本模块 Renderer，保留既有动态 patch 锚点。"""

        return self._identity_port._create_terminal_renderer()

    @property
    def is_processing(self) -> bool:
        return self._core_runtime.harness.is_running

    @property
    def session_state(self) -> SessionIdentityState:
        return self._session_state

    @property
    def session_id(self) -> str:
        return self._session_state.id

    @property
    def session_start_time(self) -> str:
        return self._session_state.started_at

    @property
    def permission_mode(self) -> PermissionMode:
        """返回当前权限模式的只读视图。"""

        return self._permission_controller.mode

    @property
    def is_aborted(self) -> bool:
        """最近一次运行是否已收到取消请求。"""

        return self._runtime_coordinator.execution.cancelled

    @property
    def core_runtime(self) -> LionAgentRuntime:
        """返回供应用会话层订阅事件与读取消息快照的 Core Runtime。"""
        return self._core_runtime

    @property
    def mcp_enabled(self) -> bool:
        """返回当前根 Agent 是否允许首次对话时发现 MCP 工具。"""

        return self._mcp_enabled

    @property
    def _project_identity(self) -> ProjectIdentity:
        return self._session_memory_coord.project_identity

    def _load_project_context_files(self, identity: ProjectIdentity) -> tuple[Any, ...]:
        """为协调器保留项目指令加载的可测试宿主边界。"""

        return load_project_context_files(
            cwd=self.tool_context.cwd,
            identity=identity,
        )

    @property
    def _session_memory_repository(self) -> SessionMemoryRepository:
        return self._session_memory_coord.session_memory_repository

    @property
    def _session_memory(self) -> SessionMemory | None:
        return self._session_memory_coord.session_memory

    @_session_memory.setter
    def _session_memory(self, value: SessionMemory | None) -> None:
        self._session_memory_coord.session_memory = value

    @property
    def _session_memory_error(self) -> str | None:
        return self._session_memory_coord.session_memory_error

    @_session_memory_error.setter
    def _session_memory_error(self, value: str | None) -> None:
        self._session_memory_coord.session_memory_error = value

    @property
    def _project_context_files(self) -> tuple[Any, ...]:
        return self._session_memory_coord.project_context_files

    @property
    def _project_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        return self._session_memory_coord.project_memory_overlays

    @property
    def _memory_coordinator(self) -> MemoryCoordinator:
        return self._session_memory_coord.memory_coordinator

    @_memory_coordinator.setter
    def _memory_coordinator(self, value: Any) -> None:
        self._session_memory_coord.memory_coordinator = value

    @property
    def _memory_injector(self) -> MemoryContextInjector:
        return self._session_memory_coord.memory_injector

    @property
    def _last_memory_injection(self) -> MemoryInjectionReport:
        return self._session_memory_coord.last_memory_injection

    @_last_memory_injection.setter
    def _last_memory_injection(self, value: MemoryInjectionReport) -> None:
        self._session_memory_coord.last_memory_injection = value

    @property
    def _turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        return self._session_memory_coord.turn_memory_overlays

    @_turn_memory_overlays.setter
    def _turn_memory_overlays(self, value: tuple[MemoryOverlay, ...]) -> None:
        self._session_memory_coord.turn_memory_overlays = value

    @property
    def session_memory(self) -> SessionMemory | None:
        """返回最近的有效短期状态；初次读取损坏文件时为 None。"""

        return self._session_memory

    @property
    def session_memory_error(self) -> str | None:
        """返回最近一次 Session Memory 加载错误，供前端显式提示。"""

        return self._session_memory_error

    def show_session_memory(self) -> str:
        """读取并展示当前项目短期状态，不触碰 JSONL transcript。"""

        return self._session_memory_coord.show_session_memory()

    def show_active_task(self) -> str:
        """读取活动任务的最小视图。"""

        return self._session_memory_coord.show_active_task()

    def switch_session_task(self, task: str) -> str:
        """持久化新的活动任务，并把旧任务保留为待继续事项。"""

        return self._session_memory_coord.switch_session_task(task)

    def finish_session_task(self) -> str:
        """结束当前任务并计算受限的长期候选，候选不会直接写入 Auto Memory。"""

        return self._session_memory_coord.finish_session_task()

    def create_session_handoff(self) -> str:
        """从当前短期状态生成并保存 handoff，供下一会话直接续接。"""

        return self._session_memory_coord.create_session_handoff()

    def _editable_session_memory(self) -> SessionMemory:
        """重载可安全写入的项目状态；损坏文件绝不被命令覆盖。"""

        return self._session_memory_coord._editable_session_memory()

    def _save_session_memory(self, memory: SessionMemory) -> None:
        """保存命令产生的短期状态，不改动当前轮已固定的 Overlay。"""

        self._session_memory_coord._save_session_memory(memory)

    def _reload_project_memory(self) -> None:
        """重新读取当前项目指令，始终保持在人写文件的只读边界内。"""

        self._session_memory_coord._reload_project_memory()

    def _build_turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        """组合本轮不可变的项目、Session 与 Auto Memory。"""

        return self._session_memory_coord._build_turn_memory_overlays()

    def _prepare_turn_memory_snapshot(self, user_message: str) -> None:
        """压缩后固定三层 Overlay，当前预取结果只留给下一轮。"""

        self._session_memory_coord._prepare_turn_memory_snapshot(user_message)

    def abort(self) -> None:
        self._runtime_coordinator.abort()

    # 应用层只通过这些语义方法访问会话，不接触 Core Runtime 的所有权细节。

    @property
    def cwd(self) -> Path:
        return Path(self.tool_context.cwd)

    @property
    def provider_name(self) -> str:
        return self._provider_manager.view.provider_kind

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return self._core_runtime.messages

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        return self._core_runtime.subscribe(listener)

    async def prompt(self, content: str) -> None:
        await self.chat(content)

    async def continue_(self) -> None:
        await self._core_runtime.continue_()

    def steer(self, content: str) -> QueueSnapshot:
        return self._core_runtime.steer(content)

    def follow_up(self, content: str) -> QueueSnapshot:
        return self._core_runtime.follow_up(content)

    def queue_snapshot(self) -> QueueSnapshot:
        return self._core_runtime.queue_snapshot()

    def cancel(self) -> None:
        self.abort()

    @property
    def cancelled(self) -> bool:
        return self.is_aborted

    async def compact_for_overflow(self) -> bool:
        return await self.compact_core_context_for_overflow()

    async def aclose(self) -> None:
        await self.close()

    async def resume(self, session_id: str) -> bool:
        return await self.restore_session_id(session_id)

    async def restore_latest(self) -> bool:
        return await self.restore_latest_session()

    async def new_session(self) -> None:
        await self.clear_history()

    def token_usage(self) -> UsageSnapshot:
        return self.get_token_usage()

    def provider_config(self) -> dict[str, Any]:
        return self.get_api_config()

    def configure_provider(self, **kwargs: Any) -> None:
        self.configure_api(**kwargs)

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

    def _emit_subagent_status(
        self,
        agent_type: str,
        description: str,
        *,
        started: bool,
    ) -> None:
        self._status_sink.emit(agent_type, description, started=started)

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self.confirm_fn = fn
        self._autonomy.set_confirm(fn)

    def set_plan_approval_fn(self, fn: Callable[[str], Awaitable[dict]] | None) -> None:
        self.plan.set_approval_fn(fn)

    # ─── Plan 模式切换 ───────────────────────────────────────

    def toggle_plan_mode(self) -> str:
        return self.plan.toggle()

    def get_token_usage(self) -> UsageSnapshot:
        return self._usage.snapshot()

    # ─── 运行时模型/凭证配置（TUI /model 的后端）──────────────

    @property
    def api_configured(self) -> bool:
        return self._provider_manager.api_configured

    def get_api_config(self) -> dict:
        """返回当前 Provider 配置的兼容投影。"""
        return self._provider_manager.get_api_config()

    def configure_api(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None:
        """在空闲态原子切换模型/凭证，并保留 canonical history。"""
        self._provider_manager.configure(
            model=model,
            api_key=api_key,
            api_base=api_base,
            anthropic_base_url=anthropic_base_url,
            use_openai=use_openai,
        )

    def set_thinking(self, enabled: bool) -> str:
        """切换 Thinking，并把实际生效级别写入当前 Core Session。"""
        return self._provider_manager.set_thinking(enabled)

    # ─── Core 路径 Thinking 档位(Tau 6 档)─────────────────────

    @property
    def thinking_level(self) -> str:
        """Core 路径当前 thinking 档位(off..xhigh)。"""
        return self._provider_manager.view.thinking_level

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        """当前后端支持的 thinking 档位(v1 两后端均返回全 6 档)。"""
        return self._provider_manager.available_thinking_levels

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        """设定 thinking 档位并热重建 Core Provider,持久化档位变更。

        与布尔 ``set_thinking(bool)`` 接口互不影响:本方法采用
        Tau 6 档词汇;档位经归一化,未变则直接返回,不重建不落盘。
        """
        return self._provider_manager.set_thinking_level(level)

    def cycle_thinking_level(self) -> ThinkingLevel:
        """循环到下一档并持久化(供 TUI shift+tab 与 /thinking 无参调用)。"""
        return self._provider_manager.cycle_thinking_level()

    def _build_core_provider(self, thinking_level: ThinkingLevel) -> ModelProvider:
        """用当前凭证与指定档位构建一个新 Core Provider。"""
        return self._provider_manager.build_provider(thinking_level)

    def _create_provider(self, **kwargs: Any) -> ModelProvider:
        """在调用时读取本模块 factory，保留测试替身的动态 patch 锚点。"""
        return _agent_provider_factory(**kwargs)

    # ─── 主对话入口 ──────────────────────────────────────────

    async def chat(self, user_message: str) -> None:
        await self._runtime_coordinator.chat(user_message)

    # ─── 子 Agent 单次运行入口 ───────────────────────────────

    async def run_once(self, prompt: str) -> dict:
        return await self._runtime_coordinator.run_once(prompt)

    # ─── 结构化单次运行入口（评测 / 非终端消费者）────────────

    async def run(self, prompt: str, *, timeout: float | None = None) -> AgentRunResult:
        """运行一次并返回结构化结果，供评测系统等不依赖终端文本的消费者使用。

        与 chat() 的差异：捕获最终文本、轮次、token、成本与停止原因，并在模型异常
        或超时时返回结构化结果而非抛出。turns 口径与 max_turns 一致，只计执行了工具
        的轮次，不含末尾纯文本轮。timeout 到期后直接取消承载 chat() 的任务，因此首次
        MCP 初始化也受同一超时约束；chat() 可能吞掉 CancelledError，这里统一改写原因。

        注意：tool_error 当前不会触发——工具异常由 ToolRuntime 转成错误内容回传，
        Agent 会继续运行直到 completed 或其他边界；该枚举值保留供未来需要时使用。
        调用方负责在结束时 await agent.close() 释放 MCP 等外部资源。
        """
        return await self._runtime_coordinator.run(prompt, timeout=timeout)

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

    async def compact(self) -> None:
        await self._runtime_coordinator.compact()

    async def dream(self) -> str:
        """显式整合当前项目 Memory，并返回本次文件变更摘要。"""
        if self.plan.is_active:
            raise RuntimeError("Plan 模式为只读，退出后才能执行 /dream")
        return await self._session_memory_coord.dream()

    def _refresh_dynamic_system_context(self) -> None:
        """刷新 Dream 修改 Auto Memory 后的动态系统提示词尾部。"""

        if not self._refresh_dynamic_context_enabled:
            return
        self._prompt_composer.set_dynamic_context(
            build_dynamic_system_context(self.tool_registry.deferred_tool_names())
        )

    def _refresh_memory_context_after_dream(self, filenames: list[str]) -> None:
        """丢弃旧预取，并让本会话后续请求看到 Dream 后的索引和文件内容。"""
        self._session_memory_coord._refresh_memory_context_after_dream(filenames)

    async def learn_from_current_session(self) -> str:
        """运行一次内置 Meta-Skill，并按其结论直接沉淀当前会话经验。"""
        return await self._learning.learn_from_current_session()

    # ─── /goal 追踪 ──────────────────────────────────────────
    # 每轮结束后由独立评估模型检查 Stop-hook 条件；未满足的原因进入下一轮，
    # 满足或判定不可能时停止。评估契约集中在 autonomy.py。

    @property
    def active_goal(self) -> dict | None:
        """活动目标(状态由 AutonomyRuntime 拥有)。"""
        return self._autonomy.active_goal

    @property
    def goal_stop(self) -> bool:
        return self._autonomy.goal_stop

    @property
    def pending_wakeup(self) -> dict | None:
        return self._autonomy.pending_wakeup

    @property
    def loop_stop(self) -> bool:
        return self._autonomy.loop_stop

    @property
    def auto_consecutive_denials(self) -> int:
        """Auto Mode 连续拒绝计数(状态由 AutonomyRuntime 拥有)。"""
        return self._autonomy.auto_consecutive_denials

    @property
    def auto_total_denials(self) -> int:
        return self._autonomy.auto_total_denials

    def set_goal(self, condition: str) -> str:
        """设置活动目标并返回首轮执行指令。"""
        return self._autonomy.set_goal(condition)

    def show_goal(self) -> None:
        """处理无参数 /goal,显示当前目标状态。"""
        self._autonomy.show_goal()

    async def pursue_goal(self, directive: str) -> None:
        """持续执行运行->评估->反馈,直到目标终止条件出现。"""
        await self._autonomy.pursue_goal(directive)

    async def _run_evaluator_query(
        self,
        system: str,
        messages: list[AgentMessage],
        max_tokens: int = 512,
    ) -> str:
        """兼容内部测试 seam；实际查询由 live ModelQuery 执行。"""

        return await self._model_query.complete_messages(
            system=system,
            messages=messages,
            max_output_tokens=max_tokens,
        )

    async def _run_classifier_query(
        self, system: str, user: str, max_tokens: int
    ) -> str:
        """兼容内部测试 seam；实际查询由 live ModelQuery 执行。"""
        return await self._model_query.complete_text(
            system=system,
            user=user,
            max_output_tokens=max_tokens,
        )

    def _extract_last_assistant_text(self) -> str:
        """提取最近一轮 assistant 文本;实现在 AutonomyRuntime。"""
        return self._autonomy._extract_last_assistant_text()

    # ─── /loop：定时或自主节奏 ───────────────────────────────
    # /goal 被动决定是否继续，/loop 则用固定间隔或 schedule_wakeup 主动安排下一轮。

    async def run_loop(self, raw_input: str) -> None:
        """解析 /loop 输入并驱动对应模式;格式错误时直接返回。"""
        await self._autonomy.run_loop(raw_input)

    async def _run_loop_dynamic(self, spec: dict) -> None:
        """动态 /loop 驱动;实现在 AutonomyRuntime,保留入口供内部测试。"""
        await self._autonomy._run_loop_dynamic(spec)

    def stop_loop(self) -> None:
        """通知正在运行的 /loop 在最近的检查点停止。"""
        self._autonomy.stop_loop()

    def stop_goal(self) -> None:
        """通知 /goal 在下一轮边界停止;正在进行的调用由 abort() 单独取消。"""
        self._autonomy.stop_goal()

    # ─── Auto Mode：transcript 分类器权限门 ───────────────────
    # auto 模式用分类器替代人工确认：deny 仍是硬边界，只读工具走快路径，
    # 其余动作由 LLM 根据不含推理的 transcript 投影判断。

    async def _classify_tool_call(
        self,
        tool_name: str,
        inp: Mapping[str, JSONValue],
    ) -> dict:
        """以两阶段分类器决定工具调用,返回 allow/deny/confirm。"""
        return await self._autonomy._classify_tool_call(tool_name, inp)

    def _child_agent_config(self) -> ChildAgentConfig:
        """返回 typed 子 Agent 配置，不把 ProviderManager 传入 child factory。"""

        kwargs = self._provider_manager.child_api_kwargs()
        return ChildAgentConfig(
            model=str(kwargs["model"]),
            api_key=str(kwargs["api_key"]),
            api_base=kwargs.get("api_base"),
            anthropic_base_url=kwargs.get("anthropic_base_url"),
            terminal_output=self._terminal_output,
        )

    # ─── 会话持久化 ──────────────────────────────────────────

    async def restore_core_session(self, session_id: str) -> bool:
        """从 JSONL 重建 Harness 唯一历史，并继续追加同一 Session。"""
        return await self._runtime_coordinator.restore_core_session(session_id)

    def _reload_session_memory(self) -> None:
        """重载当前项目状态；损坏文件仅暴露错误，绝不回写空状态。"""

        self._session_memory_coord._reload_session_memory()

    def _report_session_memory_error(self) -> None:
        self._session_memory_coord._report_session_memory_error()

    async def _update_session_memory_after_turn(
        self,
        user_message: str,
        turn_start_index: int,
    ) -> None:
        """保存本轮确定性工具事实，再以受限模型 patch 补充任务语义。"""

        await self._session_memory_coord._update_session_memory_after_turn(
            user_message,
            turn_start_index,
            semantic_extractor=self._extract_session_memory_semantics,
        )

    async def _extract_session_memory_semantics(
        self,
        memory: SessionMemory,
        user_message: str,
        assistant_text: str,
    ) -> dict[str, object]:
        """让 side query 只提炼目标和交接语义，不接管工具事实。"""

        return await self._session_memory_coord._extract_session_memory_semantics(
            memory,
            user_message,
            assistant_text,
        )

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

    def _is_snippable_tool(self, name: str) -> bool:
        try:
            tool = self.tool_registry.resolve(name)
        except LookupError:
            return False
        return tool.capabilities.result_policy == "snippable"

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

    # ─── 外部资源与 Memory 预取 ──────────────────────────────

    async def close(self) -> None:
        """释放 Capability、MCP 子进程等外部资源，确保进程正常退出（issue #8）。"""
        await self._runtime_coordinator.close()

    async def _confirm_hook_trust(self, message: str) -> bool:
        # 项目 Hook 信任独立于工具权限；--yolo 也不能替仓库代码自动取得信任。
        if self.permission_mode == "dontAsk":
            return False
        return await self._confirm_dangerous(message)

    async def _confirm_dangerous(self, command: str) -> bool:
        return await self._confirmation.confirm(command)


_ORIGINAL_AGENT_SEMANTIC_EXTRACTOR = Agent._extract_session_memory_semantics
