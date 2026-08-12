"""Agent 核心循环：统一 Anthropic 与 OpenAI 兼容后端的流式调用、上下文压缩、
Plan 模式、子 Agent、权限与预算控制。整体分层参考 Claude Code 的公开设计。
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from .agent_runtime import (
    AgentRunResult,
    AgentRuntimeCoordinator,
    LionAgentRuntime,
)
from .autonomy_runtime import AutonomyRuntime
from .capabilities import (
    CapabilityRegistry,
    McpCapability,
    create_plan_capability,
    create_skill_capability,
    create_subagent_capability,
)
from .context import (
    ContextCompactor,
    ContextManager,
    ModelLimitsResolver,
    effective_window_tokens,
    fallback_model_limits,
)
from .core.conversation import QueueSnapshot
from .core.harness import EventListener
from .core.messages import AgentMessage, AssistantMessage, TextContent, UserMessage
from .core.provider import ModelProvider
from .execution_control import ExecutionControl
from .hooks import load_pre_tool_use_hooks
from .learning_runtime import (
    LEARN_META_SKILL_PROMPT,  # noqa: F401
    LearningRuntime,
)
from .memory_runtime import (
    MemoryContextInjector,
    MemoryCoordinator,
    MemoryInjectionReport,
    MemoryOverlay,
    ProviderTextQueryService,
)
from .observers import TerminalRenderer
from .permission_state import (
    PermissionController,
    PermissionMode,
    PermissionState,
)
from .plan_runtime import PlanRuntime, PlanState
from .project_identity import ProjectIdentity, resolve_project_identity
from .prompt import (
    build_dynamic_system_context,
    build_static_system_prompt,
    load_project_context_files,
)
from .provider_manager import (
    ConfigurationRecorder,
    MemoryQuerySink,
    ModelContextControl,
    ProviderManager,
    ProviderRuntimePort,
    ProviderState,
    ProviderView,
)
from .providers.factory import create_provider
from .providers.oneshot import complete_text
from .providers.thinking import (
    ThinkingLevel,
)
from .session_identity import SessionIdentityState
from .session_memory import (
    SessionMemory,
    SessionMemoryRepository,
)
from .session_memory_coordinator import SessionMemoryCoordinator
from .session_runtime import (
    SessionRecorder,
    SessionRepository,
    legacy_session_messages,
    list_legacy_sessions,
    load_legacy_session,
)
from .skill_runtime import SkillRuntime
from .subagent_factory import SubagentFactory
from .subagent_runtime import SubagentExecutor
from .tooling import ToolEnvironment, ToolRegistry, ToolRuntime
from .tooling.builtin import create_builtin_tools
from .tooling.context import ToolContext
from .tooling.internal import create_internal_tools
from .tooling.middleware import (
    AuditMiddleware,
    CancellationMiddleware,
    PermissionMiddleware,
    PreToolHookMiddleware,
    ReadFreshnessMiddleware,
    ResultPolicyMiddleware,
)
from .tooling.permission import PermissionPolicy
from .tooling.result_store import ResultStore
from .tooling.types import JSONValue
from .tools import ToolDef
from .ui import (
    print_confirmation,
    print_error,
    print_info,
    print_sub_agent_end,
    print_sub_agent_start,
)
from .usage import BudgetPolicy, UsageLedger, UsageSnapshot

# ─── Thinking 能力检测 ──────────────────────────────────────


class _DeferredProviderRuntimePort(ProviderRuntimePort):
    """在组合根完成 Runtime 构造前暂存 ProviderManager 的端口。"""

    def __init__(self) -> None:
        self._runtime: AgentRuntimeCoordinator | None = None

    def bind(self, runtime: AgentRuntimeCoordinator) -> None:
        self._runtime = runtime

    @property
    def is_running(self) -> bool:
        return self._runtime is not None and self._runtime.core_runtime.harness.is_running

    def replace_provider(self, provider: ModelProvider) -> ModelProvider:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        return self._runtime.core_runtime.replace_provider(provider)

    def set_model(self, model: str) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.core_runtime.set_model(model)


class _DeferredModelContextControl(ModelContextControl):
    """把 Provider 派生服务更新转给现有 RuntimeCoordinator。"""

    def __init__(self) -> None:
        self._runtime: AgentRuntimeCoordinator | None = None

    def bind(self, runtime: AgentRuntimeCoordinator) -> None:
        self._runtime = runtime

    def replace_context_compactor(self, compactor: ContextCompactor) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.replace_context_compactor(compactor)

    def invalidate_model_limit_cache(self, model: str) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.invalidate_model_limit_cache(model)


class _MemoryQuerySinkAdapter(MemoryQuerySink):
    """只向 ProviderManager 暴露 Memory 的 query service 写入口。"""

    def __init__(self, coordinator: SessionMemoryCoordinator) -> None:
        self._coordinator = coordinator

    def set_query_service(self, service: ProviderTextQueryService) -> None:
        self._coordinator.set_query_service(service)


class _SessionRecorderConfigurationRecorder(ConfigurationRecorder):
    """将 Manager 的同步配置命令适配到已有异步 SessionRecorder。"""

    def __init__(self) -> None:
        self._recorder: Callable[[], SessionRecorder | None] | None = None
        self._schedule: Callable[
            [Callable[[], Coroutine[Any, Any, object]]], None
        ] | None = None

    def bind(
        self,
        recorder: Callable[[], SessionRecorder | None],
        schedule: Callable[[Callable[[], Coroutine[Any, Any, object]]], None],
    ) -> None:
        self._recorder = recorder
        self._schedule = schedule

    def record_configuration_change(
        self,
        previous: ProviderView,
        current: ProviderView,
    ) -> None:
        recorder_getter = self._recorder
        schedule = self._schedule
        if recorder_getter is None or schedule is None:
            return
        recorder = recorder_getter()
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

        schedule(persist_configuration)


class _DeferredBackgroundScheduler:
    """在 RuntimeCoordinator 创建后才转发后台清理任务。"""

    def __init__(self) -> None:
        self._runtime: AgentRuntimeCoordinator | None = None

    def bind(self, runtime: AgentRuntimeCoordinator) -> None:
        self._runtime = runtime

    def __call__(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.schedule_background_operation(operation)


# ─── Agent ──────────────────────────────────────────────────


class Agent:
    """协调模型调用、工具执行和会话状态的主运行时对象。"""

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
    ):
        self._permission_controller = PermissionController(
            PermissionState(mode=permission_mode)
        )
        self.is_sub_agent = is_sub_agent
        self._terminal_output = terminal_output
        # 评测根 Agent 必须阻止机器级 MCP 发现；默认值保留 CLI/TUI 语义。
        self._mcp_enabled = mcp_enabled
        self._notice_fn: Callable[[str, Literal["info", "error"]], None] | None = None
        self._pre_tool_use_hooks = load_pre_tool_use_hooks()
        self.confirm_fn = confirm_fn
        self.effective_window = effective_window_tokens(fallback_model_limits(model))
        self._session_state = SessionIdentityState(
            uuid.uuid4().hex[:8],
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._session_repository = session_repository or SessionRepository()
        execution = ExecutionControl()
        self._usage = UsageLedger()
        self._budget = BudgetPolicy(
            max_cost_usd=max_cost_usd,
            max_turns=max_turns,
        )

        # /goal、/loop 与 Auto Mode 的状态和协调循环由 AutonomyRuntime 拥有。
        self._autonomy = AutonomyRuntime(
            self,
            usage=self._usage,
            budget=self._budget,
        )
        self._learning = LearningRuntime(self)

        # 当前异步任务用于把 Ctrl+C 传播到正在等待的模型或工具调用。
        self._current_task: asyncio.Task | None = None
        # 最近一次 chat/run 的终止原因，供 run() 结构化返回；chat 自身不读取。
        self._last_stop_reason: str | None = None

        # Core 路径采用 Tau 6 档词汇(off..xhigh);由 ``thinking`` 开关推导初始档,
        # 运行中经 set_thinking_level/cycle_thinking_level 调整并热重建 Provider。
        initial_provider_kind = "openai-compatible" if api_base else "anthropic"
        initial_api_key = api_key or os.environ.get(
            "OPENAI_API_KEY" if initial_provider_kind == "openai-compatible" else "ANTHROPIC_API_KEY",
            "",
        )
        initial_thinking_level: ThinkingLevel = "medium" if thinking else "off"

        # 记录文件读取时的 mtime，落实“先读后改”并检测外部并发修改。
        self._read_file_state: dict[str, float] = {}

        if tool_registry is not None and custom_tools is not None:
            raise ValueError("tool_registry and custom_tools cannot be combined")
        _created_own_registry = tool_registry is None
        selected_tool_names = (
            {tool["name"] for tool in custom_tools}
            if custom_tools is not None
            else None
        )
        # 根 Agent 拥有 MCP 生命周期；子 Agent 只接收共享环境的非拥有视图。
        self.tool_environment = tool_environment or ToolEnvironment(
            owns_mcp_manager=not is_sub_agent
        )
        self._mcp_manager = self.tool_environment.mcp_manager
        self._mcp_initialized = False
        self._subagent_factory = SubagentFactory(self)
        self._subagent_executor = SubagentExecutor(
            self._subagent_factory,
            self._usage,
            self._emit_subagent_status,
        )
        self._skill_runtime = SkillRuntime(self._subagent_executor)
        self.plan = PlanRuntime(
            self,
            self._permission_controller,
            PlanState(),
        )

        if _created_own_registry:
            self.tool_registry = ToolRegistry()
            for tool in [*create_builtin_tools(), *create_internal_tools()]:
                if selected_tool_names is None or tool.name in selected_tool_names:
                    self.tool_registry.register(tool)
        else:
            self.tool_registry = cast(ToolRegistry, tool_registry)

        self._register_capabilities(
            mcp_enabled=mcp_enabled,
            is_sub_agent=is_sub_agent,
            selected_tool_names=selected_tool_names,
            created_own_registry=_created_own_registry,
        )

        # 系统提示词按前缀缓存拆成静态核心和动态尾部。项目指令改由 Provider
        # Overlay 注入，既不破坏缓存边界，也不污染 canonical Session history。
        if custom_system_prompt:
            self._static_system_prompt = custom_system_prompt
            self._dynamic_system_context = ""
        else:
            self._static_system_prompt = build_static_system_prompt()
            self._dynamic_system_context = build_dynamic_system_context(
                self.tool_registry.deferred_tool_names()
            )
        self._base_system_prompt = (
            self._static_system_prompt + "\n\n" + self._dynamic_system_context
            if self._dynamic_system_context
            else self._static_system_prompt
        )
        self._system_prompt = self._base_system_prompt
        self.plan.initialize()
        self.tool_context = ToolContext(
            session=self._session_state,
            cancellation=execution.cancellation,
            cwd=Path.cwd(),
            registry=self.tool_registry,
            permission=self._permission_controller,
            plan=self.plan,
            read_file_state=self._read_file_state,
            confirm_fn=self._confirm_dangerous,
            hooks=self._pre_tool_use_hooks,
            confirm_hook_trust=self._confirm_hook_trust,
            auto_permission_fn=self._classify_tool_call,
        )
        self._session_memory_coord = SessionMemoryCoordinator(
            self,
            identity=resolve_project_identity(self.tool_context.cwd),
            repository=session_memory_repository,
        )
        self._permission_policy = PermissionPolicy(cwd=self.tool_context.cwd)
        self._result_store = ResultStore()
        self.tool_runtime = ToolRuntime(
            self.tool_registry,
            self.tool_context,
            [
                CancellationMiddleware(),
                PreToolHookMiddleware(),
                PermissionMiddleware(
                    self._permission_policy,
                    self._permission_controller,
                ),
                ReadFreshnessMiddleware(),
                ResultPolicyMiddleware(self._result_store),
                AuditMiddleware(),
            ],
        )
        runtime_context_manager = context_manager or ContextManager(
            is_snippable_tool=self._is_snippable_tool
        )

        provider_runtime_port = _DeferredProviderRuntimePort()
        model_context_control = _DeferredModelContextControl()
        memory_query_sink = _MemoryQuerySinkAdapter(self._session_memory_coord)
        configuration_recorder = _SessionRecorderConfigurationRecorder()
        background_scheduler = _DeferredBackgroundScheduler()
        self._provider_manager = ProviderManager(
            state=ProviderState(
                model=model,
                provider_kind=initial_provider_kind,
                api_key=initial_api_key,
                openai_base_url=api_base,
                anthropic_base_url=anthropic_base_url,
                thinking_enabled=thinking,
                thinking_level=initial_thinking_level,
            ),
            runtime=provider_runtime_port,
            context=model_context_control,
            memory=memory_query_sink,
            recorder=configuration_recorder,
            provider_factory=self._create_provider,
            schedule_background_operation=background_scheduler,
        )
        provider = self._provider_manager.build_provider()
        self._runtime_coordinator = AgentRuntimeCoordinator(
            usage=self._usage,
            budget=self._budget,
            identity=self,
            session=self,
            memory=self,
            execution=execution,
            provider=provider,
            model=self.model,
            tool_runtime=self.tool_runtime,
            context_manager=runtime_context_manager,
            context_compactor=context_compactor,
            model_limits_resolver=model_limits_resolver or ModelLimitsResolver(),
            provider_manager=self._provider_manager,
        )
        provider_runtime_port.bind(self._runtime_coordinator)
        model_context_control.bind(self._runtime_coordinator)
        configuration_recorder.bind(
            lambda: self._runtime_coordinator.session_recorder,
            self._runtime_coordinator.schedule_background_operation,
        )
        background_scheduler.bind(self._runtime_coordinator)
        self._session_memory_coord.set_query_service(
            self._build_core_memory_query_service()
        )

    def _register_capabilities(
        self,
        *,
        mcp_enabled: bool,
        is_sub_agent: bool,
        selected_tool_names: set[str] | None,
        created_own_registry: bool,
    ) -> None:
        """注册 Agent 能力并将其提供的工具接入自有注册表。"""
        self._capability_registry = CapabilityRegistry()
        mcp_is_root = (
            mcp_enabled and not is_sub_agent and self.tool_environment.owns_mcp_manager
        )
        self._mcp_capability = McpCapability(
            mcp_manager=self._mcp_manager,
            tool_registry=self.tool_registry,
            emit_notice=lambda msg: self._emit_notice(msg),
            is_already_initialized=lambda: self._mcp_initialized,
            mark_initialized=lambda: setattr(self, "_mcp_initialized", True),
            is_root=mcp_is_root,
        )
        self._capability_registry.register(self._mcp_capability.spec)
        self._capability_registry.register(create_skill_capability(self._skill_runtime))
        self._capability_registry.register(
            create_subagent_capability(self._subagent_executor)
        )
        self._capability_registry.register(create_plan_capability(self.plan))

        for source in self._capability_registry.tool_sources:
            for tool in source.tools():
                if created_own_registry:
                    if selected_tool_names is None or tool.name in selected_tool_names:
                        self.tool_registry.register(tool)
                    continue
                try:
                    was_active = self.tool_registry.is_active(tool.name)
                    self.tool_registry.resolve(tool.name)
                except LookupError:
                    continue
                self.tool_registry.register(
                    tool,
                    replace=True,
                    activate=was_active,
                )

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

    def _create_terminal_renderer(self) -> TerminalRenderer:
        """在调用时读取本模块 Renderer，保留既有动态 patch 锚点。"""

        return TerminalRenderer()

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

    def _build_core_memory_query_service(self):
        """构建绑定当前 Core Provider 的文本查询服务。"""

        return self._session_memory_coord._build_core_memory_query_service()

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

    def set_notice_fn(
        self,
        fn: Callable[[str, Literal["info", "error"]], None] | None,
    ) -> None:
        """设置实例级状态通知回调；未设置时继续直接输出到终端。"""

        self._notice_fn = fn

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        if self._notice_fn is not None:
            self._notice_fn(message, role)
        elif self._terminal_output:
            (print_error if role == "error" else print_info)(message)

    def _emit_subagent_status(
        self,
        agent_type: str,
        description: str,
        *,
        started: bool,
    ) -> None:
        if not self._terminal_output:
            return
        if started:
            print_sub_agent_start(agent_type, description)
        else:
            print_sub_agent_end(agent_type, description)

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self.confirm_fn = fn

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
        return create_provider(**kwargs)

    # ─── 主对话入口 ──────────────────────────────────────────

    async def _before_turn_capabilities(self) -> None:
        """Invoke all registered TurnParticipant hooks before a chat starts.

        This replaces the former ``_ensure_mcp_tools`` with a generic
        capability-driven entry point.  Agent does not know which
        capabilities exist or what they do.
        """
        for participant in self._capability_registry.turn_participants:
            await participant.before_turn()

    async def _after_turn_capabilities(self) -> None:
        """调用所有已注册 Capability 的轮次结束钩子。"""
        for participant in self._capability_registry.turn_participants:
            await participant.after_turn()

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
        return await self._session_memory_coord.dream()

    def _refresh_dynamic_system_context(self) -> None:
        """刷新 Dream 修改 Auto Memory 后的动态系统提示词尾部。"""

        if not self._dynamic_system_context:
            return
        self._dynamic_system_context = build_dynamic_system_context(
            self.tool_registry.deferred_tool_names()
        )
        self._base_system_prompt = (
            self._static_system_prompt + "\n\n" + self._dynamic_system_context
        )
        self.plan.refresh_prompt()

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

    def _canonical_side_messages(self, messages: list) -> list[AgentMessage]:
        """把 {role, content} 字典消息转为 canonical,供 Provider side-query。"""
        canonical: list[AgentMessage] = []
        for message in messages:
            content = str(message.get("content", ""))
            if message.get("role") == "assistant":
                canonical.append(
                    AssistantMessage(
                        model=self.model,
                        content=[TextContent(text=content)],
                        stop_reason="stop",
                    )
                )
            else:
                canonical.append(UserMessage(content=content))
        return canonical

    async def _run_evaluator_query(
        self, system: str, messages: list, max_tokens: int = 512
    ) -> str:
        """通过当前 Provider 发送保留 role 的评估请求，并返回模型文本。

        与只接受单条 user 消息的 sideQuery 分开，避免 Memory 接口限制目标评估结构。
        """
        del max_tokens
        return await complete_text(
            self._core_runtime.provider,
            model=self.model,
            system=system,
            messages=self._canonical_side_messages(messages),
        )

    async def _run_classifier_query(
        self, system: str, user: str, max_tokens: int
    ) -> str:
        """通过当前 Provider 发送单消息分类请求。"""
        return await self._build_core_memory_query_service().complete(
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

    def _child_api_kwargs(self) -> dict:
        """子 Agent fork 的模型与凭证参数:继承父级当前后端的 key/base。

        此前 fork 只传 api_base 不传 key,/model 配置(无环境变量)的用户
        fork 出的子 Agent 是无凭证的。
        """
        return {
            **self._provider_manager.child_api_kwargs(),
            "terminal_output": self._terminal_output,
        }

    def _child_permission_mode(self) -> PermissionMode:
        """确定子 Agent 继承的权限模式。

        plan 与 auto 必须向下传递；否则默认 bypassPermissions 会让主模型借子 Agent
        绕过只读或分类器限制。其他模式允许子 Agent 独立执行已授权任务。
        """
        if self.permission_mode == "plan":
            return "plan"
        if self.permission_mode == "auto":
            return "auto"
        return "bypassPermissions"

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

    async def _close_capabilities(self) -> None:
        """关闭 Capability 声明的资源，具体顺序由 Registry 负责。"""
        await self._capability_registry.close_all()

    async def _confirm_hook_trust(self, message: str) -> bool:
        # 项目 Hook 信任独立于工具权限；--yolo 也不能替仓库代码自动取得信任。
        if self.permission_mode == "dontAsk":
            return False
        return await self._confirm_dangerous(message)

    async def _confirm_dangerous(self, command: str) -> bool:
        if self._terminal_output:
            print_confirmation(command)
        if self.confirm_fn:
            return await self.confirm_fn(command)
        # 无异步回调时退回阻塞式终端输入，仅用于直接嵌入 Agent 的场景。
        try:
            answer = input("  Allow? (y/n): ")
            return answer.lower().startswith("y")
        except EOFError:
            return False
