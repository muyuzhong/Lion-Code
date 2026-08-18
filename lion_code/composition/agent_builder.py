"""Agent Composition Root：一次性组装所有 concrete runtime。

唯一入口是 ``build_agent_composition(profile)``：Profile 提供不可变组合选择，
builder 一次性创建 graph。Feature-specific construction branch 只存在于
``_normalize_profile``，不进入 Kernel/Harness。
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agent_runtime import AgentRuntimeCoordinator
from ..capabilities import (
    CapabilityRegistry,
    CapabilityRuntime,
    CapabilitySpec,
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
from ..observers import TerminalRenderer
from ..permission_state import PermissionController, PermissionState
from ..plan_runtime import PlanRuntime, PlanState
from ..prompt import (
    PromptComposer,
    build_dynamic_system_context,
    build_static_system_prompt,
)
from ..provider_manager import ProviderKind, ProviderManager, ProviderState
from ..providers.factory import create_provider
from ..providers.thinking import ThinkingLevel
from ..session_identity import SessionIdentityState
from ..session_runtime import SessionRepository
from ..skill_runtime import SkillRuntime
from ..subagent_factory import ChildAgentConfig, SubagentFactory
from ..subagent_runtime import SubagentExecutor
from ..tooling import (
    CommandExecutionBackend,
    LocalCommandExecutionBackend,
    ToolPermissionStrategy,
    ToolRegistry,
    ToolRuntime,
)
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
from ..tooling.types import LionTool
from ..usage import BudgetPolicy, UsageLedger
from .config import AgentConfig, AgentDependencies
from .ports import (
    ConfirmationController,
    DeferredBackgroundScheduler,
    DeferredModelContextControl,
    DeferredProviderRuntimePort,
    NoticeController,
    PlanHost,
    RuntimeIdentityPort,
    SessionRecorderConfigurationRecorder,
    SessionStatePort,
    SubagentStatusSink,
)
from .profiles import (
    NEUTRAL_SYSTEM_PROMPT,
    CodingProfile,
    FullProfile,
    MinimalProfile,
    Profile,
)

# 内置 Capability 选择名：只在 Composition Root 内部使用，Profile 不接受该集合。
_CAP_SKILL = "skill"
_CAP_SUBAGENT = "subagent"
_CAP_PLAN = "plan"


@dataclass(slots=True)
class AgentComposition:
    """Composition Root 完成后交给 facade 的显式对象集合。

    Feature 字段（plan / subagent）在 Bare 图中为 ``None``：
    调用方按所选 capabilities 判空，不创建 Null 对象。
    """

    session_state: SessionIdentityState
    session_repository: SessionRepository
    usage: UsageLedger
    budget: BudgetPolicy
    tool_registry: ToolRegistry
    plan: PlanRuntime | None
    subagent_factory: SubagentFactory | None
    subagent_executor: SubagentExecutor | None
    skill_runtime: SkillRuntime | None
    capability_registry: CapabilityRegistry
    capability_runtime: CapabilityRuntime
    prompt_composer: PromptComposer
    tool_context: ToolContext
    permission_policy: ToolPermissionStrategy
    tool_runtime: ToolRuntime
    provider_manager: ProviderManager
    runtime_coordinator: AgentRuntimeCoordinator
    notices: NoticeController
    confirmation: ConfirmationController
    status_sink: SubagentStatusSink | None


@dataclass(slots=True)
class _ProfileSelection:
    """Profile 归一化结果；builder 内部的一次性值，不导出。"""

    config: AgentConfig
    dependencies: AgentDependencies
    capabilities: frozenset[str]
    builtin_tools: bool
    caller_tools: tuple[LionTool, ...]
    base_prompt: str
    dynamic_prompt_enabled: bool
    permission_strategy: ToolPermissionStrategy | None
    command_backend: CommandExecutionBackend | None
    extension_specs: tuple[CapabilitySpec, ...]


@dataclass(slots=True)
class _FoundationGraph:
    dependencies: AgentDependencies
    cwd: Path
    provider_factory: Any
    hooks_loader: Any
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
    tool_registry: ToolRegistry
    created_own_registry: bool
    plan: PlanRuntime | None


@dataclass(slots=True)
class _ResolvedDependencies:
    dependencies: AgentDependencies
    cwd: Path
    provider_factory: Any
    hooks_loader: Any
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
    capability_runtime: CapabilityRuntime


@dataclass(slots=True)
class _ToolingGraph:
    prompt_composer: PromptComposer
    tool_context: ToolContext
    permission_policy: ToolPermissionStrategy
    result_store: ResultStore
    tool_runtime: ToolRuntime
    context_manager: ContextManager
    session_port: SessionStatePort


def build_agent_composition(profile: Profile) -> AgentComposition:
    """按固定顺序创建 Agent object graph，并返回一次性 composition result。

    Profile 是组合选择的唯一来源：``MinimalProfile`` 构造零内置 Capability 的
    Bare 图，``CodingProfile`` 构造 backend 绑定的 Coding 工具形态，
    ``FullProfile`` 固定组合 Plan/SubAgent/默认 Skill。
    """

    selection = _normalize_profile(profile)
    config = selection.config
    foundation = _build_foundation(selection)
    notices = foundation.notices
    confirmation = foundation.confirmation
    status_sink = foundation.status_sink
    usage = foundation.usage
    budget = foundation.budget
    session_state = foundation.session_state
    session_repository = foundation.session_repository
    tool_registry = foundation.tool_registry
    plan = foundation.plan

    provider_graph = _build_provider_graph(config, foundation)
    provider_manager = provider_graph.provider_manager
    identity_port = _build_identity_port(config, foundation, provider_manager)

    capability_graph = _build_capability_graph(
        foundation,
        provider_manager,
        identity_port,
        selection,
    )
    subagent_factory = capability_graph.subagent_factory
    subagent_executor = capability_graph.subagent_executor
    skill_runtime = capability_graph.skill_runtime
    capability_registry = capability_graph.capability_registry
    capability_runtime = capability_graph.capability_runtime

    tooling_graph = _build_tooling_graph(selection, foundation, capability_registry)
    prompt_composer = tooling_graph.prompt_composer
    tool_context = tooling_graph.tool_context
    permission_policy = tooling_graph.permission_policy
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
    return AgentComposition(
        session_state=session_state,
        session_repository=session_repository,
        usage=usage,
        budget=budget,
        tool_registry=tool_registry,
        plan=plan,
        subagent_factory=subagent_factory,
        subagent_executor=subagent_executor,
        skill_runtime=skill_runtime,
        capability_registry=capability_registry,
        capability_runtime=capability_runtime,
        prompt_composer=prompt_composer,
        tool_context=tool_context,
        permission_policy=permission_policy,
        tool_runtime=tool_runtime,
        provider_manager=provider_manager,
        runtime_coordinator=runtime_coordinator,
        notices=notices,
        confirmation=confirmation,
        status_sink=status_sink,
    )


def _normalize_profile(profile: Profile) -> _ProfileSelection:
    """把 Profile value 归一化为 builder 内部的一次性选择。

    Feature-specific construction branch 只存在于本函数：Profile 类型本身
    表达内置 Capability 组合，不暴露任意 capability-name set。
    """
    if isinstance(profile, MinimalProfile):
        return _ProfileSelection(
            config=profile.config,
            dependencies=profile.dependencies,
            capabilities=frozenset(),
            builtin_tools=False,
            caller_tools=profile.tools,
            base_prompt=profile.system_prompt or NEUTRAL_SYSTEM_PROMPT,
            dynamic_prompt_enabled=False,
            permission_strategy=profile.permission_strategy,
            command_backend=None,
            extension_specs=(),
        )
    if isinstance(profile, CodingProfile):
        return _ProfileSelection(
            config=profile.config,
            dependencies=profile.dependencies,
            capabilities=frozenset(),
            builtin_tools=True,
            caller_tools=profile.extra_tools,
            base_prompt=profile.system_prompt or build_static_system_prompt(),
            dynamic_prompt_enabled=profile.system_prompt is None,
            permission_strategy=profile.permission_strategy,
            command_backend=profile.command_backend,
            extension_specs=(),
        )
    if isinstance(profile, FullProfile):
        return _ProfileSelection(
            config=profile.config,
            dependencies=profile.dependencies,
            capabilities=frozenset(
                {_CAP_SKILL, _CAP_SUBAGENT, _CAP_PLAN},
            ),
            builtin_tools=True,
            caller_tools=profile.extra_tools,
            base_prompt=profile.system_prompt or build_static_system_prompt(),
            dynamic_prompt_enabled=profile.system_prompt is None,
            permission_strategy=profile.permission_strategy,
            command_backend=profile.command_backend,
            extension_specs=profile.extension_specs,
        )
    raise TypeError(f"unsupported profile: {type(profile).__name__}")


def _resolve_dependencies(
    selection: _ProfileSelection,
) -> _ResolvedDependencies:
    config = selection.config
    deps = selection.dependencies
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
    if selection.capabilities & {_CAP_SUBAGENT, _CAP_SKILL}:
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
        dynamic_context_builder=(
            deps.dynamic_system_context_builder or build_dynamic_system_context
        ),
        renderer_factory=deps.terminal_renderer_factory or TerminalRenderer,
        notices=notices,
        confirmation=confirmation,
        permission_controller=confirmation.permission,
        status_sink=status_sink,
    )


def _build_foundation(selection: _ProfileSelection) -> _FoundationGraph:
    resolved = _resolve_dependencies(selection)
    config = selection.config
    deps = resolved.dependencies
    cwd = resolved.cwd
    provider_factory = resolved.provider_factory
    hooks_loader = resolved.hooks_loader
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

    created_own_registry = deps.tool_registry is None
    if not created_own_registry and selection.caller_tools:
        raise ValueError("tool_registry cannot be combined with profile tools")
    tool_registry = deps.tool_registry or ToolRegistry()
    if created_own_registry:
        for tool in selection.caller_tools:
            tool_registry.register(tool)
        if selection.builtin_tools:
            backend = selection.command_backend or LocalCommandExecutionBackend()
            for tool in [*create_builtin_tools(backend), *create_internal_tools()]:
                tool_registry.register(tool)

    if _CAP_PLAN in selection.capabilities:
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
        tool_registry=tool_registry,
        created_own_registry=created_own_registry,
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
    foundation: _FoundationGraph,
    provider_manager: ProviderManager,
    identity_port: RuntimeIdentityPort,
    selection: _ProfileSelection,
) -> _CapabilityGraph:
    capabilities = selection.capabilities

    def child_config() -> ChildAgentConfig:
        return _child_config(provider_manager, identity_port)

    capability_registry = CapabilityRegistry()
    subagent_factory: SubagentFactory | None = None
    subagent_executor: SubagentExecutor | None = None
    if _CAP_SUBAGENT in capabilities or _CAP_SKILL in capabilities:
        if foundation.status_sink is None:
            raise RuntimeError("subagent capability requires status sink")
        subagent_factory = SubagentFactory(
            registry=foundation.tool_registry,
            child_config=child_config,
        )
        subagent_executor = SubagentExecutor(
            subagent_factory,
            foundation.usage,
            foundation.status_sink.emit,
        )
    skill_runtime: SkillRuntime | None = None
    if _CAP_SKILL in capabilities:
        if subagent_executor is None:
            raise RuntimeError("skill capability requires subagent machinery")
        skill_runtime = SkillRuntime(subagent_executor)

    if _CAP_SKILL in capabilities and skill_runtime is not None:
        capability_registry.register(create_skill_capability(skill_runtime))
    if _CAP_SUBAGENT in capabilities and subagent_executor is not None:
        capability_registry.register(create_subagent_capability(subagent_executor))
    if _CAP_PLAN in capabilities and foundation.plan is not None:
        capability_registry.register(create_plan_capability(foundation.plan))
    for spec in selection.extension_specs:
        capability_registry.register(spec)
    _install_capability_tools(foundation, capability_registry)
    return _CapabilityGraph(
        subagent_factory=subagent_factory,
        subagent_executor=subagent_executor,
        skill_runtime=skill_runtime,
        capability_registry=capability_registry,
        capability_runtime=CapabilityRuntime(capability_registry),
    )


def _install_capability_tools(
    foundation: _FoundationGraph,
    capability_registry: CapabilityRegistry,
) -> None:
    for source in capability_registry.tool_sources:
        for tool in source.tools():
            if foundation.created_own_registry:
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
    selection: _ProfileSelection,
    foundation: _FoundationGraph,
    capability_registry: CapabilityRegistry,
) -> _ToolingGraph:
    prompt_composer = PromptComposer(
        stable_base_prompt=selection.base_prompt,
        dynamic_context=(
            foundation.dynamic_context_builder(
                foundation.tool_registry.deferred_tool_names()
            )
            if selection.dynamic_prompt_enabled
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
    permission_policy = selection.permission_strategy or PermissionPolicy(
        cwd=foundation.cwd
    )
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
