"""Agent Composition Root：一次性组装所有 concrete runtime。"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agent_runtime import AgentRuntimeCoordinator
from ..autonomy_runtime import AutonomyRuntime
from ..capabilities import (
    CapabilityRegistry,
    CapabilityRuntime,
    McpCapability,
    create_plan_capability,
    create_skill_capability,
    create_subagent_capability,
)
from ..context import (
    ContextManager,
    ModelLimitsResolver,
    effective_window_tokens,
    fallback_model_limits,
)
from ..dream import DreamCoordinator
from ..dream_adapter import RestrictedDreamAgentFactory
from ..execution_control import ExecutionControl
from ..hooks import load_pre_tool_use_hooks
from ..learning_runtime import LearningRuntime
from ..memory_runtime import ProviderTextQueryService
from ..model_query import ProviderModelQuery
from ..observers import TerminalRenderer
from ..permission_state import PermissionController, PermissionState
from ..plan_runtime import PlanRuntime, PlanState
from ..project_identity import ProjectIdentity, resolve_project_identity
from ..prompt import (
    PromptComposer,
    build_dynamic_system_context,
    build_static_system_prompt,
    load_project_context_files,
)
from ..provider_manager import ProviderKind, ProviderManager, ProviderState
from ..providers.factory import create_provider
from ..providers.thinking import ThinkingLevel
from ..session_identity import SessionIdentityState
from ..session_memory_coordinator import SessionMemoryCoordinator
from ..session_runtime import SessionRepository
from ..skill_runtime import SkillRuntime
from ..subagent_factory import ChildAgentConfig, SubagentFactory
from ..subagent_runtime import SubagentExecutor
from ..tooling import ToolEnvironment, ToolRegistry, ToolRuntime
from ..tooling.builtin import create_builtin_tools
from ..tooling.context import ToolContext
from ..tooling.internal import create_internal_tools
from ..tooling.middleware import (
    AuditMiddleware,
    CancellationMiddleware,
    PermissionMiddleware,
    PreToolHookMiddleware,
    ReadFreshnessMiddleware,
    ResultPolicyMiddleware,
)
from ..tooling.permission import PermissionPolicy
from ..tooling.result_store import ResultStore
from ..usage import BudgetPolicy, UsageLedger
from .config import AgentConfig, AgentDependencies
from .ports import (
    ConfirmationController,
    DeferredAutoPermission,
    DeferredBackgroundScheduler,
    DeferredMemoryQuerySink,
    DeferredModelContextControl,
    DeferredProviderRuntimePort,
    McpLifecycleState,
    MemoryQuerySinkAdapter,
    MemoryTurnPort,
    NoticeController,
    NoticeSinkAdapter,
    PlanHost,
    RuntimeIdentityPort,
    SessionMemorySnapshotView,
    SessionRecorderConfigurationRecorder,
    SessionStatePort,
    SubagentStatusSink,
)


@dataclass(slots=True)
class AgentComposition:
    """Composition Root 完成后交给 facade 的显式对象集合。"""

    permission_controller: PermissionController
    session_state: SessionIdentityState
    session_repository: SessionRepository
    execution: ExecutionControl
    usage: UsageLedger
    budget: BudgetPolicy
    read_file_state: dict[str, float]
    pre_tool_use_hooks: list[Any]
    tool_environment: ToolEnvironment
    tool_registry: ToolRegistry
    mcp_manager: Any
    mcp_state: McpLifecycleState
    plan: PlanRuntime
    subagent_factory: SubagentFactory
    subagent_executor: SubagentExecutor
    skill_runtime: SkillRuntime
    capability_registry: CapabilityRegistry
    mcp_capability: McpCapability
    capability_runtime: CapabilityRuntime
    refresh_dynamic_context_enabled: bool
    prompt_composer: PromptComposer
    tool_context: ToolContext
    permission_policy: PermissionPolicy
    result_store: ResultStore
    tool_runtime: ToolRuntime
    context_manager: ContextManager
    provider_manager: ProviderManager
    runtime_coordinator: AgentRuntimeCoordinator
    session_memory_coordinator: SessionMemoryCoordinator
    autonomy: AutonomyRuntime
    learning: LearningRuntime
    model_query: ProviderModelQuery
    identity_port: RuntimeIdentityPort
    session_port: SessionStatePort
    memory_port: MemoryTurnPort
    notices: NoticeController
    confirmation: ConfirmationController
    status_sink: SubagentStatusSink


def build_agent_composition(
    config: AgentConfig,
    dependencies: AgentDependencies | None = None,
) -> AgentComposition:
    """按固定顺序创建 Agent object graph，并返回一次性 composition result。"""

    deps = dependencies or AgentDependencies()
    cwd = Path.cwd()
    provider_factory = deps.provider_factory or create_provider
    hooks_loader = deps.pre_tool_use_hooks_loader or load_pre_tool_use_hooks
    resolve_identity = deps.project_identity_resolver or resolve_project_identity
    context_loader = deps.project_context_loader or _default_project_context_loader
    dynamic_context_builder = (
        deps.dynamic_system_context_builder or build_dynamic_system_context
    )
    renderer_factory = deps.terminal_renderer_factory or TerminalRenderer

    notices = NoticeController(
        print_info=deps.print_info or _noop_print,
        print_error=deps.print_error or _noop_print,
    )
    confirmation = ConfirmationController(
        permission=PermissionController(PermissionState(mode=config.permission_mode)),
        terminal_output=config.terminal_output,
        print_confirmation=deps.print_confirmation or _noop_print,
        confirm_fn=deps.confirm_fn,
    )
    permission_controller = confirmation.permission
    status_sink = SubagentStatusSink(
        terminal_output=config.terminal_output,
        start=deps.print_sub_agent_start or _noop_status,
        end=deps.print_sub_agent_end or _noop_status,
    )
    execution = ExecutionControl()
    usage = UsageLedger()
    budget = BudgetPolicy(
        max_cost_usd=config.max_cost_usd,
        max_turns=config.max_turns,
    )
    session_state = SessionIdentityState(
        uuid.uuid4().hex[:8],
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    session_repository = deps.session_repository or SessionRepository()
    read_file_state: dict[str, float] = {}
    mcp_state = McpLifecycleState()

    if deps.tool_registry is not None and config.custom_tools is not None:
        raise ValueError("tool_registry and custom_tools cannot be combined")
    created_own_registry = deps.tool_registry is None
    selected_tool_names = (
        {str(tool["name"]) for tool in config.custom_tools}
        if config.custom_tools is not None
        else None
    )
    tool_environment = deps.tool_environment or ToolEnvironment(
        owns_mcp_manager=not config.is_sub_agent
    )
    mcp_manager = tool_environment.mcp_manager
    tool_registry = deps.tool_registry or ToolRegistry()
    if created_own_registry:
        for tool in [*create_builtin_tools(), *create_internal_tools()]:
            if selected_tool_names is None or tool.name in selected_tool_names:
                tool_registry.register(tool)

    notice_sink = NoticeSinkAdapter(notices)
    plan = PlanRuntime(
        PlanHost(session_state, notices),
        permission_controller,
        PlanState(),
    )
    plan.initialize()

    initial_provider_kind: ProviderKind = (
        "openai-compatible" if config.api_base else "anthropic"
    )
    initial_api_key = config.api_key or os.environ.get(
        "OPENAI_API_KEY"
        if initial_provider_kind == "openai-compatible"
        else "ANTHROPIC_API_KEY",
        "",
    )
    initial_thinking_level: ThinkingLevel = "medium" if config.thinking else "off"
    provider_runtime_port = DeferredProviderRuntimePort()
    model_context_control = DeferredModelContextControl()
    memory_query_sink = DeferredMemoryQuerySink()
    configuration_recorder = SessionRecorderConfigurationRecorder()
    background_scheduler = DeferredBackgroundScheduler()
    provider_manager = ProviderManager(
        state=ProviderState(
            model=config.model,
            provider_kind=initial_provider_kind,
            api_key=initial_api_key,
            openai_base_url=config.api_base,
            anthropic_base_url=config.anthropic_base_url,
            thinking_enabled=config.thinking,
            thinking_level=initial_thinking_level,
        ),
        runtime=provider_runtime_port,
        context=model_context_control,
        memory=memory_query_sink,
        recorder=configuration_recorder,
        provider_factory=provider_factory,
        schedule_background_operation=background_scheduler,
    )
    provider = provider_manager.build_provider()

    def child_config() -> ChildAgentConfig:
        return _child_config(provider_manager, identity_port)

    subagent_factory = SubagentFactory(
        registry=tool_registry,
        environment=tool_environment,
        child_config=child_config,
        permission=permission_controller,
    )
    subagent_executor = SubagentExecutor(
        subagent_factory,
        usage,
        status_sink.emit,
    )
    skill_runtime = SkillRuntime(subagent_executor)

    capability_registry = CapabilityRegistry()
    mcp_is_root = (
        config.mcp_enabled
        and not config.is_sub_agent
        and tool_environment.owns_mcp_manager
    )
    mcp_capability = McpCapability(
        mcp_manager=mcp_manager,
        tool_registry=tool_registry,
        emit_notice=notices.emit,
        is_already_initialized=lambda: mcp_state.initialized,
        mark_initialized=lambda: setattr(mcp_state, "initialized", True),
        is_root=mcp_is_root,
    )
    capability_registry.register(mcp_capability.spec)
    capability_registry.register(create_skill_capability(skill_runtime))
    capability_registry.register(create_subagent_capability(subagent_executor))
    capability_registry.register(create_plan_capability(plan))
    for spec in deps.extra_capabilities:
        capability_registry.register(spec)
    for source in capability_registry.tool_sources:
        for tool in source.tools():
            if created_own_registry:
                if selected_tool_names is None or tool.name in selected_tool_names:
                    tool_registry.register(tool)
                continue
            try:
                was_active = tool_registry.is_active(tool.name)
                tool_registry.resolve(tool.name)
            except LookupError:
                continue
            tool_registry.register(tool, replace=True, activate=was_active)
    capability_runtime = CapabilityRuntime(capability_registry)

    refresh_dynamic_context_enabled = not bool(config.custom_system_prompt)
    prompt_composer = PromptComposer(
        stable_base_prompt=config.custom_system_prompt or build_static_system_prompt(),
        dynamic_context=(
            dynamic_context_builder(tool_registry.deferred_tool_names())
            if refresh_dynamic_context_enabled
            else ""
        ),
        layers=lambda: capability_registry.prompt_layers,
    )
    deferred_auto_permission = DeferredAutoPermission()
    tool_context = ToolContext(
        session=session_state,
        cancellation=execution.cancellation,
        cwd=cwd,
        registry=tool_registry,
        permission=permission_controller,
        plan=plan,
        read_file_state=read_file_state,
        confirm_fn=confirmation.confirm,
        hooks=hooks_loader(),
        confirm_hook_trust=confirmation.confirm_hook_trust,
        auto_permission_fn=deferred_auto_permission,
    )
    permission_policy = PermissionPolicy(cwd=cwd)
    result_store = ResultStore()
    tool_runtime = ToolRuntime(
        tool_registry,
        tool_context,
        [
            CancellationMiddleware(),
            PreToolHookMiddleware(),
            PermissionMiddleware(permission_policy, permission_controller),
            ReadFreshnessMiddleware(),
            ResultPolicyMiddleware(result_store),
            AuditMiddleware(),
        ],
    )
    context_manager = deps.context_manager or ContextManager(
        is_snippable_tool=lambda name: _is_snippable_tool(tool_registry, name)
    )
    memory_port = MemoryTurnPort()
    identity_port = RuntimeIdentityPort(
        is_sub_agent=config.is_sub_agent,
        terminal_output=config.terminal_output,
        effective_window=effective_window_tokens(fallback_model_limits(config.model)),
        api_configured=lambda: provider_manager.api_configured,
        is_aborted=lambda: execution.cancelled,
        terminal_renderer_factory=renderer_factory,
        notices=notices,
    )
    session_port = SessionStatePort(
        session_state=session_state,
        session_repository=session_repository,
        plan=plan,
        tool_context=tool_context,
        tool_environment=tool_environment,
    )
    runtime_coordinator = AgentRuntimeCoordinator(
        usage=usage,
        budget=budget,
        identity=identity_port,
        session=session_port,
        memory=memory_port,
        execution=execution,
        capabilities=capability_runtime,
        get_system=prompt_composer.get_system,
        provider=provider,
        model=provider_manager.model,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
        context_compactor=deps.context_compactor,
        model_limits_resolver=deps.model_limits_resolver or ModelLimitsResolver(),
        provider_manager=provider_manager,
    )
    provider_runtime_port.bind(runtime_coordinator)
    model_context_control.bind(runtime_coordinator)
    configuration_recorder.bind(
        lambda: runtime_coordinator.session_recorder,
        runtime_coordinator.schedule_background_operation,
    )
    background_scheduler.bind(runtime_coordinator)

    query = ProviderModelQuery(
        provider=lambda: runtime_coordinator.core_runtime.provider,
        model=lambda: provider_manager.model,
        available=lambda: provider_manager.api_configured,
    )
    memory_query = ProviderTextQueryService(
        provider=provider,
        model=lambda: provider_manager.model,
    )
    identity = resolve_identity(cwd)
    session_memory_coord: SessionMemoryCoordinator | None = None

    def load_session_memory() -> Any:
        if session_memory_coord is None:
            return None
        if session_memory_coord.session_memory_error is not None:
            return None
        return session_memory_coord.session_memory

    def refresh_dynamic_context() -> None:
        if not refresh_dynamic_context_enabled:
            return
        prompt_composer.set_dynamic_context(
            dynamic_context_builder(tool_registry.deferred_tool_names())
        )

    dream_factory = RestrictedDreamAgentFactory(
        registry=tool_registry,
        environment=tool_environment,
        child_config=child_config,
    )
    dream = DreamCoordinator(
        repository=session_repository,
        identity=identity,
        session_memory=SessionMemorySnapshotView(load_session_memory),
        factory=dream_factory,
        usage=usage,
    )
    session_memory_coord = SessionMemoryCoordinator(
        identity=identity,
        repository=deps.session_memory_repository,
        transcript=runtime_coordinator.core_runtime,
        cancellation=execution.cancellation,
        permission=permission_controller,
        load_project_context=lambda project_identity: tuple(
            context_loader(cwd, project_identity)
        ),
        notices=notice_sink,
        query=memory_query,
        dream_runner=dream,
        is_sub_agent=config.is_sub_agent,
        status_callback=status_sink.emit,
        refresh_context=refresh_dynamic_context,
    )
    memory_port.bind(
        session_memory_coord,
        semantic_extractor=session_memory_coord._extract_session_memory_semantics,
    )
    memory_query_sink.bind(MemoryQuerySinkAdapter(session_memory_coord))
    autonomy = AutonomyRuntime(
        conversation=runtime_coordinator,
        transcript=runtime_coordinator.core_runtime,
        query=query,
        notices=notice_sink,
        cancellation=execution.cancellation,
        tool_registry=tool_registry,
        confirm=deps.confirm_fn,
        usage=usage,
        budget=budget,
    )
    deferred_auto_permission.bind(
        lambda name, arguments: autonomy._classify_tool_call(name, arguments)
    )
    learning = LearningRuntime(
        runtime_coordinator.core_runtime,
        query,
        cwd,
    )

    return AgentComposition(
        permission_controller=permission_controller,
        session_state=session_state,
        session_repository=session_repository,
        execution=execution,
        usage=usage,
        budget=budget,
        read_file_state=read_file_state,
        pre_tool_use_hooks=tool_context.hooks,
        tool_environment=tool_environment,
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        mcp_state=mcp_state,
        plan=plan,
        subagent_factory=subagent_factory,
        subagent_executor=subagent_executor,
        skill_runtime=skill_runtime,
        capability_registry=capability_registry,
        mcp_capability=mcp_capability,
        capability_runtime=capability_runtime,
        refresh_dynamic_context_enabled=refresh_dynamic_context_enabled,
        prompt_composer=prompt_composer,
        tool_context=tool_context,
        permission_policy=permission_policy,
        result_store=result_store,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
        provider_manager=provider_manager,
        runtime_coordinator=runtime_coordinator,
        session_memory_coordinator=session_memory_coord,
        autonomy=autonomy,
        learning=learning,
        model_query=query,
        identity_port=identity_port,
        session_port=session_port,
        memory_port=memory_port,
        notices=notices,
        confirmation=confirmation,
        status_sink=status_sink,
    )


def _default_project_context_loader(
    cwd: Path,
    identity: ProjectIdentity,
) -> Sequence[Any]:
    return load_project_context_files(cwd=cwd, identity=identity)


def _child_config(
    provider_manager: ProviderManager,
    identity_port: RuntimeIdentityPort,
) -> ChildAgentConfig:
    kwargs = provider_manager.child_api_kwargs()
    return ChildAgentConfig(
        model=str(kwargs["model"]),
        api_key=str(kwargs["api_key"]),
        api_base=kwargs.get("api_base"),
        anthropic_base_url=kwargs.get("anthropic_base_url"),
        terminal_output=identity_port._terminal_output,
    )


def _is_snippable_tool(registry: ToolRegistry, name: str) -> bool:
    try:
        tool = registry.resolve(name)
    except LookupError:
        return False
    return tool.capabilities.result_policy == "snippable"


def _noop_print(_message: str) -> None:
    return None


def _noop_status(_agent_type: str, _description: str) -> None:
    return None
