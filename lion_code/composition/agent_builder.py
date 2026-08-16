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
from ..execution_control import ExecutionControl
from ..hooks import load_pre_tool_use_hooks
from ..mcp_client import McpManager
from ..memory_runtime import ProviderTextQueryService
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
    DeferredBackgroundScheduler,
    DeferredModelContextControl,
    DeferredProviderRuntimePort,
    McpLifecycleState,
    NoticeController,
    NoticeSinkAdapter,
    PlanHost,
    RuntimeIdentityPort,
    SessionRecorderConfigurationRecorder,
    SessionStatePort,
    SubagentStatusSink,
)

# 内置能力名：Composition Root 的显式选择集合，Bare 图默认空集。
CAP_MCP = "mcp"
CAP_SKILL = "skill"
CAP_SUBAGENT = "subagent"
CAP_PLAN = "plan"
CAP_MEMORY = "memory"

# 短生命周期名称：PR7b 将由 Profile 取代该常量。
PRODUCT_CAPABILITIES = frozenset(
    {
        CAP_MCP,
        CAP_SKILL,
        CAP_SUBAGENT,
        CAP_PLAN,
        CAP_MEMORY,
    }
)


@dataclass(slots=True)
class AgentComposition:
    """Composition Root 完成后交给 facade 的显式对象集合。

    Feature 字段（plan / subagent / mcp / memory）在 Bare 图中为 ``None``：
    调用方按所选 capabilities 判空，不创建 Null 对象。
    """

    permission_controller: PermissionController
    session_state: SessionIdentityState
    session_repository: SessionRepository
    execution: ExecutionControl
    usage: UsageLedger
    budget: BudgetPolicy
    read_file_state: dict[str, float]
    pre_tool_use_hooks: list[Any]
    tool_environment: ToolEnvironment | None
    tool_registry: ToolRegistry
    mcp_manager: Any | None
    mcp_state: McpLifecycleState | None
    plan: PlanRuntime | None
    subagent_factory: SubagentFactory | None
    subagent_executor: SubagentExecutor | None
    skill_runtime: SkillRuntime | None
    capability_registry: CapabilityRegistry
    mcp_capability: McpCapability | None
    capability_runtime: CapabilityRuntime
    prompt_composer: PromptComposer
    tool_context: ToolContext
    permission_policy: PermissionPolicy
    result_store: ResultStore
    tool_runtime: ToolRuntime
    context_manager: ContextManager
    provider_manager: ProviderManager
    runtime_coordinator: AgentRuntimeCoordinator
    session_memory_coordinator: SessionMemoryCoordinator | None
    identity_port: RuntimeIdentityPort
    session_port: SessionStatePort
    notices: NoticeController
    confirmation: ConfirmationController
    status_sink: SubagentStatusSink | None


@dataclass(slots=True)
class _FoundationGraph:
    dependencies: AgentDependencies
    cwd: Path
    provider_factory: Any
    hooks_loader: Any
    resolve_identity: Any
    context_loader: Any
    dynamic_context_builder: Any
    renderer_factory: Any
    notices: NoticeController
    confirmation: ConfirmationController
    permission_controller: PermissionController
    status_sink: SubagentStatusSink | None
    execution: ExecutionControl
    usage: UsageLedger
    budget: BudgetPolicy
    session_state: SessionIdentityState
    session_repository: SessionRepository
    read_file_state: dict[str, float]
    mcp_state: McpLifecycleState | None
    tool_environment: ToolEnvironment | None
    mcp_manager: Any | None
    tool_registry: ToolRegistry
    created_own_registry: bool
    selected_tool_names: set[str] | None
    notice_sink: NoticeSinkAdapter | None
    plan: PlanRuntime | None


@dataclass(slots=True)
class _ResolvedDependencies:
    dependencies: AgentDependencies
    cwd: Path
    provider_factory: Any
    hooks_loader: Any
    resolve_identity: Any
    context_loader: Any
    dynamic_context_builder: Any
    renderer_factory: Any
    notices: NoticeController
    confirmation: ConfirmationController
    permission_controller: PermissionController
    status_sink: SubagentStatusSink | None


@dataclass(slots=True)
class _ProviderGraph:
    provider_runtime_port: DeferredProviderRuntimePort
    model_context_control: DeferredModelContextControl
    configuration_recorder: SessionRecorderConfigurationRecorder
    background_scheduler: DeferredBackgroundScheduler
    provider_manager: ProviderManager
    provider: Any


@dataclass(slots=True)
class _CapabilityGraph:
    subagent_factory: SubagentFactory | None
    subagent_executor: SubagentExecutor | None
    skill_runtime: SkillRuntime | None
    capability_registry: CapabilityRegistry
    mcp_capability: McpCapability | None
    capability_runtime: CapabilityRuntime


@dataclass(slots=True)
class _ToolingGraph:
    prompt_composer: PromptComposer
    tool_context: ToolContext
    permission_policy: PermissionPolicy
    result_store: ResultStore
    tool_runtime: ToolRuntime
    context_manager: ContextManager
    session_port: SessionStatePort


@dataclass(slots=True)
class _SessionGraph:
    session_memory_coordinator: SessionMemoryCoordinator | None


def build_agent_composition(
    config: AgentConfig,
    dependencies: AgentDependencies | None = None,
    *,
    capabilities: frozenset[str] = frozenset(),
) -> AgentComposition:
    """按固定顺序创建 Agent object graph，并返回一次性 composition result。

    ``capabilities`` 显式选择内置能力；默认空集即 Bare 图：不创建
    Memory/Plan/MCP/SubAgent/Skill。Full Product 由 ``PRODUCT_CAPABILITIES``
    显式选择。
    """

    foundation = _build_foundation(config, dependencies, capabilities)
    notices = foundation.notices
    confirmation = foundation.confirmation
    permission_controller = foundation.permission_controller
    status_sink = foundation.status_sink
    execution = foundation.execution
    usage = foundation.usage
    budget = foundation.budget
    session_state = foundation.session_state
    session_repository = foundation.session_repository
    read_file_state = foundation.read_file_state
    mcp_state = foundation.mcp_state
    tool_environment = foundation.tool_environment
    mcp_manager = foundation.mcp_manager
    tool_registry = foundation.tool_registry
    plan = foundation.plan

    provider_graph = _build_provider_graph(config, foundation)
    provider_manager = provider_graph.provider_manager
    identity_port = _build_identity_port(config, foundation, provider_manager)

    capability_graph = _build_capability_graph(
        config,
        foundation,
        provider_manager,
        identity_port,
        capabilities,
    )
    subagent_factory = capability_graph.subagent_factory
    subagent_executor = capability_graph.subagent_executor
    skill_runtime = capability_graph.skill_runtime
    capability_registry = capability_graph.capability_registry
    mcp_capability = capability_graph.mcp_capability
    capability_runtime = capability_graph.capability_runtime

    tooling_graph = _build_tooling_graph(
        config,
        foundation,
        capability_registry,
    )
    prompt_composer = tooling_graph.prompt_composer
    tool_context = tooling_graph.tool_context
    permission_policy = tooling_graph.permission_policy
    result_store = tooling_graph.result_store
    tool_runtime = tooling_graph.tool_runtime
    context_manager = tooling_graph.context_manager
    session_port = tooling_graph.session_port
    runtime_coordinator = _build_runtime_coordinator(
        foundation,
        provider_graph,
        capability_runtime,
        prompt_composer,
        identity_port,
        session_port,
        tool_runtime,
        context_manager,
    )
    session_graph = _build_session_graph(
        config,
        foundation,
        provider_graph,
        runtime_coordinator,
        capabilities,
    )
    session_memory_coord = session_graph.session_memory_coordinator

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
        prompt_composer=prompt_composer,
        tool_context=tool_context,
        permission_policy=permission_policy,
        result_store=result_store,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
        provider_manager=provider_manager,
        runtime_coordinator=runtime_coordinator,
        session_memory_coordinator=session_memory_coord,
        identity_port=identity_port,
        session_port=session_port,
        notices=notices,
        confirmation=confirmation,
        status_sink=status_sink,
    )


def _resolve_dependencies(
    config: AgentConfig,
    dependencies: AgentDependencies | None,
    capabilities: frozenset[str],
) -> _ResolvedDependencies:
    deps = dependencies or AgentDependencies()
    cwd = Path.cwd()
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
    status_sink = None
    if capabilities & {CAP_SUBAGENT, CAP_SKILL}:
        status_sink = SubagentStatusSink(
            terminal_output=config.terminal_output,
            start=deps.print_sub_agent_start or _noop_status,
            end=deps.print_sub_agent_end or _noop_status,
        )
    return _ResolvedDependencies(
        dependencies=deps,
        cwd=cwd,
        provider_factory=deps.provider_factory or create_provider,
        hooks_loader=deps.pre_tool_use_hooks_loader or load_pre_tool_use_hooks,
        resolve_identity=deps.project_identity_resolver or resolve_project_identity,
        context_loader=deps.project_context_loader or _default_project_context_loader,
        dynamic_context_builder=(
            deps.dynamic_system_context_builder or build_dynamic_system_context
        ),
        renderer_factory=deps.terminal_renderer_factory or TerminalRenderer,
        notices=notices,
        confirmation=confirmation,
        permission_controller=confirmation.permission,
        status_sink=status_sink,
    )


def _build_foundation(
    config: AgentConfig,
    dependencies: AgentDependencies | None,
    capabilities: frozenset[str],
) -> _FoundationGraph:
    resolved = _resolve_dependencies(config, dependencies, capabilities)
    deps = resolved.dependencies
    cwd = resolved.cwd
    provider_factory = resolved.provider_factory
    hooks_loader = resolved.hooks_loader
    resolve_identity = resolved.resolve_identity
    context_loader = resolved.context_loader
    dynamic_context_builder = resolved.dynamic_context_builder
    renderer_factory = resolved.renderer_factory
    notices = resolved.notices
    confirmation = resolved.confirmation
    permission_controller = resolved.permission_controller
    status_sink = resolved.status_sink
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
    mcp_state = McpLifecycleState() if CAP_MCP in capabilities else None

    if deps.tool_registry is not None and config.custom_tools is not None:
        raise ValueError("tool_registry and custom_tools cannot be combined")
    created_own_registry = deps.tool_registry is None
    selected_tool_names = (
        {str(tool["name"]) for tool in config.custom_tools}
        if config.custom_tools is not None
        else None
    )
    needs_tool_environment = bool(
        capabilities & {CAP_MCP, CAP_SUBAGENT, CAP_SKILL, CAP_MEMORY}
    )
    if deps.tool_environment is not None:
        tool_environment = deps.tool_environment
    elif CAP_MCP in capabilities:
        tool_environment = ToolEnvironment(
            mcp_manager=McpManager(),
            owns_mcp_manager=not config.is_sub_agent,
        )
    elif needs_tool_environment:
        tool_environment = ToolEnvironment(
            mcp_manager=None,
            owns_mcp_manager=False,
        )
    else:
        tool_environment = None
    mcp_manager = tool_environment.mcp_manager if tool_environment is not None else None
    tool_registry = deps.tool_registry or ToolRegistry()
    if created_own_registry:
        for tool in [*create_builtin_tools(), *create_internal_tools()]:
            if selected_tool_names is None or tool.name in selected_tool_names:
                tool_registry.register(tool)

    notice_sink = NoticeSinkAdapter(notices) if CAP_MEMORY in capabilities else None
    if CAP_PLAN in capabilities:
        plan: PlanRuntime | None = PlanRuntime(
            PlanHost(session_state, notices),
            PlanState(),
        )
    else:
        plan = None
    return _FoundationGraph(
        dependencies=deps,
        cwd=cwd,
        provider_factory=provider_factory,
        hooks_loader=hooks_loader,
        resolve_identity=resolve_identity,
        context_loader=context_loader,
        dynamic_context_builder=dynamic_context_builder,
        renderer_factory=renderer_factory,
        notices=notices,
        confirmation=confirmation,
        permission_controller=permission_controller,
        status_sink=status_sink,
        execution=execution,
        usage=usage,
        budget=budget,
        session_state=session_state,
        session_repository=session_repository,
        read_file_state=read_file_state,
        mcp_state=mcp_state,
        tool_environment=tool_environment,
        mcp_manager=mcp_manager,
        tool_registry=tool_registry,
        created_own_registry=created_own_registry,
        selected_tool_names=selected_tool_names,
        notice_sink=notice_sink,
        plan=plan,
    )


def _build_provider_graph(
    config: AgentConfig,
    foundation: _FoundationGraph,
) -> _ProviderGraph:
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
        recorder=configuration_recorder,
        provider_factory=foundation.provider_factory,
        schedule_background_operation=background_scheduler,
    )
    provider = foundation.dependencies.provider
    if provider is None:
        provider = provider_manager.build_provider()
    return _ProviderGraph(
        provider_runtime_port=provider_runtime_port,
        model_context_control=model_context_control,
        configuration_recorder=configuration_recorder,
        background_scheduler=background_scheduler,
        provider_manager=provider_manager,
        provider=provider,
    )


def _build_identity_port(
    config: AgentConfig,
    foundation: _FoundationGraph,
    provider_manager: ProviderManager,
) -> RuntimeIdentityPort:
    return RuntimeIdentityPort(
        is_sub_agent=config.is_sub_agent,
        terminal_output=config.terminal_output,
        effective_window=effective_window_tokens(fallback_model_limits(config.model)),
        api_configured=lambda: (
            foundation.dependencies.provider is not None
            or provider_manager.api_configured
        ),
        is_aborted=lambda: foundation.execution.cancelled,
        terminal_renderer_factory=foundation.renderer_factory,
        notices=foundation.notices,
    )


def _build_capability_graph(
    config: AgentConfig,
    foundation: _FoundationGraph,
    provider_manager: ProviderManager,
    identity_port: RuntimeIdentityPort,
    capabilities: frozenset[str],
) -> _CapabilityGraph:
    def child_config() -> ChildAgentConfig:
        return _child_config(provider_manager, identity_port)

    capability_registry = CapabilityRegistry()
    subagent_factory: SubagentFactory | None = None
    subagent_executor: SubagentExecutor | None = None
    if CAP_SUBAGENT in capabilities or CAP_SKILL in capabilities:
        if foundation.tool_environment is None or foundation.status_sink is None:
            raise RuntimeError("subagent capability requires tooling environment")
        subagent_factory = SubagentFactory(
            registry=foundation.tool_registry,
            environment=foundation.tool_environment,
            child_config=child_config,
        )
        subagent_executor = SubagentExecutor(
            subagent_factory,
            foundation.usage,
            foundation.status_sink.emit,
        )
    skill_runtime: SkillRuntime | None = None
    if CAP_SKILL in capabilities:
        if subagent_executor is None:
            raise RuntimeError("skill capability requires subagent machinery")
        skill_runtime = SkillRuntime(subagent_executor)

    mcp_capability: McpCapability | None = None
    if CAP_MCP in capabilities:
        mcp_manager = foundation.mcp_manager
        mcp_state = foundation.mcp_state
        if foundation.tool_environment is None:
            raise RuntimeError("mcp capability requires tooling environment")
        mcp_capability = McpCapability(
            mcp_manager=mcp_manager,
            tool_registry=foundation.tool_registry,
            emit_notice=foundation.notices.emit,
            is_already_initialized=lambda: (
                mcp_state.initialized if mcp_state is not None else False
            ),
            mark_initialized=lambda: (
                setattr(mcp_state, "initialized", True)
                if mcp_state is not None
                else None
            ),
            is_root=(
                config.mcp_enabled
                and not config.is_sub_agent
                and foundation.tool_environment.owns_mcp_manager
            ),
        )
        capability_registry.register(mcp_capability.spec)
    if CAP_SKILL in capabilities and skill_runtime is not None:
        capability_registry.register(create_skill_capability(skill_runtime))
    if CAP_SUBAGENT in capabilities and subagent_executor is not None:
        capability_registry.register(create_subagent_capability(subagent_executor))
    if CAP_PLAN in capabilities and foundation.plan is not None:
        capability_registry.register(create_plan_capability(foundation.plan))
    for spec in foundation.dependencies.extra_capabilities:
        capability_registry.register(spec)
    _install_capability_tools(foundation, capability_registry)
    return _CapabilityGraph(
        subagent_factory=subagent_factory,
        subagent_executor=subagent_executor,
        skill_runtime=skill_runtime,
        capability_registry=capability_registry,
        mcp_capability=mcp_capability,
        capability_runtime=CapabilityRuntime(capability_registry),
    )


def _install_capability_tools(
    foundation: _FoundationGraph,
    capability_registry: CapabilityRegistry,
) -> None:
    for source in capability_registry.tool_sources:
        for tool in source.tools():
            if foundation.created_own_registry:
                if (
                    foundation.selected_tool_names is None
                    or tool.name in foundation.selected_tool_names
                ):
                    foundation.tool_registry.register(tool)
                continue
            try:
                was_active = foundation.tool_registry.is_active(tool.name)
                foundation.tool_registry.resolve(tool.name)
            except LookupError:
                continue
            foundation.tool_registry.register(
                tool,
                replace=True,
                activate=was_active,
            )


def _build_tooling_graph(
    config: AgentConfig,
    foundation: _FoundationGraph,
    capability_registry: CapabilityRegistry,
) -> _ToolingGraph:
    refresh_dynamic_context_enabled = not bool(config.custom_system_prompt)
    prompt_composer = PromptComposer(
        stable_base_prompt=config.custom_system_prompt or build_static_system_prompt(),
        dynamic_context=(
            foundation.dynamic_context_builder(
                foundation.tool_registry.deferred_tool_names()
            )
            if refresh_dynamic_context_enabled
            else ""
        ),
        layers=lambda: capability_registry.prompt_layers,
    )
    tool_context = ToolContext(
        session=foundation.session_state,
        cancellation=foundation.execution.cancellation,
        cwd=foundation.cwd,
        registry=foundation.tool_registry,
        permission=foundation.permission_controller,
        read_file_state=foundation.read_file_state,
        confirm_fn=foundation.confirmation.confirm,
        hooks=foundation.hooks_loader(),
        confirm_hook_trust=foundation.confirmation.confirm_hook_trust,
    )
    permission_policy = PermissionPolicy(cwd=foundation.cwd)
    result_store = ResultStore()
    tool_runtime = ToolRuntime(
        foundation.tool_registry,
        tool_context,
        [
            CancellationMiddleware(),
            PreToolHookMiddleware(),
            PermissionMiddleware(
                permission_policy,
                foundation.permission_controller,
            ),
            ReadFreshnessMiddleware(),
            ResultPolicyMiddleware(result_store),
            AuditMiddleware(),
        ],
    )
    context_manager = foundation.dependencies.context_manager or ContextManager(
        is_snippable_tool=lambda name: _is_snippable_tool(
            foundation.tool_registry, name
        )
    )
    session_port = SessionStatePort(
        session_state=foundation.session_state,
        session_repository=foundation.session_repository,
        tool_context=tool_context,
        tool_environment=foundation.tool_environment,
    )
    return _ToolingGraph(
        prompt_composer=prompt_composer,
        tool_context=tool_context,
        permission_policy=permission_policy,
        result_store=result_store,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
        session_port=session_port,
    )


def _build_runtime_coordinator(
    foundation: _FoundationGraph,
    provider_graph: _ProviderGraph,
    capability_runtime: CapabilityRuntime,
    prompt_composer: PromptComposer,
    identity_port: RuntimeIdentityPort,
    session_port: SessionStatePort,
    tool_runtime: ToolRuntime,
    context_manager: ContextManager,
) -> AgentRuntimeCoordinator:
    runtime_coordinator = AgentRuntimeCoordinator(
        usage=foundation.usage,
        budget=foundation.budget,
        identity=identity_port,
        session=session_port,
        execution=foundation.execution,
        capabilities=capability_runtime,
        get_system=prompt_composer.get_system,
        provider=provider_graph.provider,
        model=provider_graph.provider_manager.model,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
        context_compactor=foundation.dependencies.context_compactor,
        model_limits_resolver=(
            foundation.dependencies.model_limits_resolver or ModelLimitsResolver()
        ),
        provider_manager=provider_graph.provider_manager,
    )
    provider_graph.provider_runtime_port.bind(runtime_coordinator)
    provider_graph.model_context_control.bind(runtime_coordinator)
    provider_graph.configuration_recorder.bind(
        lambda: runtime_coordinator.session_recorder,
        runtime_coordinator.schedule_background_operation,
    )
    provider_graph.background_scheduler.bind(runtime_coordinator)
    return runtime_coordinator


def _build_session_graph(
    config: AgentConfig,
    foundation: _FoundationGraph,
    provider_graph: _ProviderGraph,
    runtime_coordinator: AgentRuntimeCoordinator,
    capabilities: frozenset[str],
) -> _SessionGraph:
    session_memory_coord: SessionMemoryCoordinator | None = None
    if CAP_MEMORY in capabilities:
        # notice_sink 与 CAP_MEMORY 同条件创建，此处仅为类型收窄的不变量断言。
        assert foundation.notice_sink is not None
        identity = foundation.resolve_identity(foundation.cwd)
        memory_query = ProviderTextQueryService(
            provider=provider_graph.provider,
            model=lambda: provider_graph.provider_manager.model,
        )
        session_memory_coord = SessionMemoryCoordinator(
            identity=identity,
            repository=foundation.dependencies.session_memory_repository,
            transcript=runtime_coordinator.core_runtime,
            cancellation=foundation.execution.cancellation,
            load_project_context=lambda project_identity: tuple(
                foundation.context_loader(foundation.cwd, project_identity)
            ),
            notices=foundation.notice_sink,
            query=memory_query,
            is_sub_agent=config.is_sub_agent,
        )
    return _SessionGraph(session_memory_coordinator=session_memory_coord)


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
