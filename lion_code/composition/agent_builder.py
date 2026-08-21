"""Agent Composition Root：一次性组装所有 concrete runtime。

唯一入口是 ``build_agent_composition(profile, config=config, bindings=bindings)``：
三轴在此汇合——Profile 表达 WHAT TO BUILD（产品形态），AgentConfig 表达
HOW IT RUNS（运行策略值），RuntimeBindings 表达 WITH WHAT（具体实现绑定）。
这是唯一允许同时看见三者的地方；Feature-specific construction branch 只存在于
``_normalize_profile``，不进入 Kernel/Harness。

Object graph 按可拓扑排序的固定顺序构建，无 Deferred 二段式绑定：

    foundation → ContextRuntime → ConversationRuntime → SessionRuntime
              → AgentRuntime → ProviderController

ProviderController 最后创建，构造时直接持有 Conversation/Context/Session
三个窄端口；AgentRuntime 与 ProviderController 互不引用。
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ..capabilities import (
    CapabilityRegistry,
    CapabilityRuntime,
    CapabilitySpec,
)
from ..capabilities.agent_state import create_agent_state_capability
from ..capabilities.git_status import create_git_status_capability
from ..capabilities.plan.capability import create_plan_capability
from ..capabilities.plan.runtime import PlanRuntime, PlanState
from ..capabilities.skill.capability import create_skill_capability
from ..capabilities.skill.runtime import SkillRuntime
from ..capabilities.subagent.capability import create_subagent_capability
from ..capabilities.subagent.factory import ChildAgentConfig, SubagentFactory
from ..capabilities.subagent.runtime import SubagentExecutor
from ..context import (
    ContextManager,
    ModelLimitsResolver,
    ProviderContextCompactor,
    effective_window_tokens,
    fallback_model_limits,
)
from ..hooks import load_pre_tool_use_hooks
from ..observers import TerminalRenderer
from ..permission_state import PermissionController, PermissionState
from ..prompt import (
    PromptComposer,
    build_dynamic_system_context,
    build_static_system_prompt,
)
from ..providers.config import DEFAULT_ANTHROPIC_BASE_URL
from ..providers.factory import create_provider
from ..providers.thinking import ThinkingLevel
from ..runtime.agent import AgentRuntime
from ..runtime.context import ContextRuntime
from ..runtime.conversation import ConversationRuntime
from ..runtime.execution import ExecutionControl
from ..runtime.provider import (
    ProviderConfigurationProjection,
    ProviderController,
    ProviderFactory,
    ProviderKind,
    ProviderState,
    build_provider_for_state,
)
from ..runtime.session import SessionRuntime
from ..runtime.session_identity import SessionIdentityState
from ..session_runtime import SessionRepository
from ..tooling import (
    LocalCommandExecutionBackend,
    ToolPermissionStrategy,
    ToolRegistry,
    ToolRuntime,
)
from ..tooling.audit import ExecutionAuditLog
from ..tooling.builtin import create_builtin_tools
from ..tooling.context import ToolContext
from ..tooling.egress_guard import EgressGuardMiddleware, EgressWhitelist, host_of
from ..tooling.internal import create_internal_tools
from ..tooling.middleware import (
    AuditMiddleware,
    CancellationMiddleware,
    PermissionMiddleware,
    PreToolHookMiddleware,
    ReadFreshnessMiddleware,
    ResultPolicyMiddleware,
    ToolMiddleware,
    WorkspaceSnapshotMiddleware,
)
from ..tooling.output_sanitizer import OutputSanitizerMiddleware
from ..tooling.permission import PermissionPolicy
from ..tooling.result_store import ResultStore
from ..tooling.secret_provider import load_secret_store
from ..tooling.snapshot import WorkspaceSnapshot
from ..tooling.types import LionTool
from ..usage import BudgetPolicy, UsageLedger
from .bindings import RuntimeBindings
from .config import AgentConfig
from .ports import (
    ConfirmationController,
    NoticeController,
    PlanHost,
    RuntimeIdentityPort,
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
class RuntimeComposition:
    """Runtime 平面的分层组合结果：编排者、三个 Owner 与 Provider 命令面。"""

    agent: AgentRuntime
    conversation: ConversationRuntime
    session: SessionRuntime
    context: ContextRuntime
    provider_controller: ProviderController
    usage: UsageLedger
    budget: BudgetPolicy


@dataclass(slots=True)
class CapabilityComposition:
    """Capability 平面：通用 registry/runtime 与 product controls。"""

    registry: CapabilityRegistry
    runtime: CapabilityRuntime
    plan: PlanRuntime | None
    subagent_factory: SubagentFactory | None
    subagent_executor: SubagentExecutor | None
    skill_runtime: SkillRuntime | None


@dataclass(slots=True)
class ToolingComposition:
    """Tooling 平面：工具注册、执行运行时与提示组装。"""

    registry: ToolRegistry
    runtime: ToolRuntime
    context: ToolContext
    permission_policy: ToolPermissionStrategy
    prompt_composer: PromptComposer


@dataclass(slots=True)
class InteractionComposition:
    """Interaction 平面：通知、确认与子 Agent 状态呈现。"""

    notices: NoticeController
    confirmation: ConfirmationController
    status_sink: SubagentStatusSink | None


@dataclass(slots=True)
class AgentComposition:
    """Composition Root 完成后交给 facade 的分层对象集合。

    Feature 字段（plan / subagent / skill）在 Bare 图中为 ``None``：
    调用方按所选 capabilities 判空，不创建 Null 对象。
    """

    runtime: RuntimeComposition
    capabilities: CapabilityComposition
    tooling: ToolingComposition
    interaction: InteractionComposition


@dataclass(slots=True)
class _ProfileSelection:
    """Profile 归一化结果：只含组合选择（WHAT），不含 config 与 bindings。"""

    capabilities: frozenset[str]
    builtin_tools: bool
    caller_tools: tuple[LionTool, ...]
    base_prompt: str
    dynamic_prompt_enabled: bool
    extension_specs: tuple[CapabilitySpec, ...]


@dataclass(slots=True)
class _FoundationGraph:
    bindings: RuntimeBindings
    cwd: Path
    provider_factory: ProviderFactory
    hooks_loader: Callable[[], list[Any]]
    dynamic_context_builder: Callable[[list[str]], str]
    renderer_factory: Callable[[], TerminalRenderer]
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


def build_agent_composition(
    profile: Profile,
    *,
    config: AgentConfig,
    bindings: RuntimeBindings,
) -> AgentComposition:
    """按固定顺序创建 Agent object graph，并返回一次性分层 composition result。

    Profile / AgentConfig / RuntimeBindings 三轴只在此汇合：``MinimalProfile``
    构造零内置 Capability 的 Bare 图，``CodingProfile`` 构造 Coding 工具形态，
    ``FullProfile`` 固定组合 Plan/SubAgent/默认 Skill；config 提供运行策略，
    bindings 提供全部 concrete infrastructure。
    """

    selection = _normalize_profile(profile)
    foundation = _build_foundation(selection, config, bindings)
    execution = foundation.execution
    usage = foundation.usage
    session_state = foundation.session_state
    session_repository = foundation.session_repository

    provider_state = _build_provider_state(config)
    initial_thinking_level: ThinkingLevel = "medium" if config.thinking else "off"
    provider = foundation.bindings.provider.provider
    if provider is None:
        provider = build_provider_for_state(
            foundation.provider_factory,
            provider_state,
            provider_state.thinking_level,
        )

    provider_projection = ProviderConfigurationProjection(
        _state=provider_state,
        _provider_ready=foundation.bindings.provider.provider is not None,
    )

    identity_port = _build_identity_port(
        foundation,
        api_configured=provider_projection.is_api_configured,
    )

    capability_graph = _build_capability_graph(
        foundation,
        identity_port,
        selection,
        child_config=partial(_child_config, provider_projection, identity_port),
    )

    tooling_graph = _build_tooling_graph(
        selection,
        foundation,
        capability_graph.capability_registry,
        provider_hosts=frozenset(
            host
            for host in (
                host_of(config.anthropic_base_url or DEFAULT_ANTHROPIC_BASE_URL),
                host_of(config.api_base) if config.api_base else None,
            )
            if host
        ),
    )

    context = ContextRuntime(
        context_manager=tooling_graph.context_manager,
        context_compactor=foundation.bindings.session.context_compactor,
        model_limits_resolver=(
            foundation.bindings.provider.model_limits_resolver or ModelLimitsResolver()
        ),
        usage=usage,
        execution=execution,
        initial_effective_window=effective_window_tokens(
            fallback_model_limits(config.model)
        ),
    )

    conversation = ConversationRuntime(
        provider=provider,
        model=provider_state.model,
        get_system=tooling_graph.prompt_composer.get_system,
        tool_runtime=tooling_graph.tool_runtime,
        cancellation=execution.cancellation,
        cancel_callback=execution.cancel,
        prepare_context=context.prepare_context,
    )
    if foundation.bindings.session.context_compactor is None:
        context.replace_context_compactor(
            ProviderContextCompactor(
                provider=provider,
                get_model=lambda: conversation.model,
            )
        )

    session = SessionRuntime(
        session_state=session_state,
        repository=session_repository,
        capabilities=capability_graph.capability_runtime,
        is_sub_agent=config.is_sub_agent,
        cwd=foundation.cwd,
        initial_model=provider_state.model,
        initial_thinking_level=initial_thinking_level,
    )

    agent_runtime = AgentRuntime(
        conversation=conversation,
        session=session,
        context=context,
        identity=identity_port,
        execution=execution,
        usage=usage,
        budget=foundation.budget,
    )

    provider_controller = ProviderController(
        state=provider_state,
        conversation=conversation,
        context=context,
        recorder=session,
        provider_factory=foundation.provider_factory,
        get_live_model=lambda: conversation.model,
        configuration_projection=provider_projection,
    )

    return AgentComposition(
        runtime=RuntimeComposition(
            agent=agent_runtime,
            conversation=conversation,
            session=session,
            context=context,
            provider_controller=provider_controller,
            usage=usage,
            budget=foundation.budget,
        ),
        capabilities=CapabilityComposition(
            registry=capability_graph.capability_registry,
            runtime=capability_graph.capability_runtime,
            plan=foundation.plan,
            subagent_factory=capability_graph.subagent_factory,
            subagent_executor=capability_graph.subagent_executor,
            skill_runtime=capability_graph.skill_runtime,
        ),
        tooling=ToolingComposition(
            registry=foundation.tool_registry,
            runtime=tooling_graph.tool_runtime,
            context=tooling_graph.tool_context,
            permission_policy=tooling_graph.permission_policy,
            prompt_composer=tooling_graph.prompt_composer,
        ),
        interaction=InteractionComposition(
            notices=foundation.notices,
            confirmation=foundation.confirmation,
            status_sink=foundation.status_sink,
        ),
    )


def _normalize_profile(profile: Profile) -> _ProfileSelection:
    """把 Profile value 归一化为 builder 内部的一次性组合选择。

    Feature-specific construction branch 只存在于本函数：Profile 类型本身
    表达内置 Capability 组合，不暴露任意 capability-name set；config 与
    bindings 不在归一化范围内。
    """
    if isinstance(profile, MinimalProfile):
        return _ProfileSelection(
            capabilities=frozenset(),
            builtin_tools=False,
            caller_tools=profile.tools,
            base_prompt=profile.system_prompt or NEUTRAL_SYSTEM_PROMPT,
            dynamic_prompt_enabled=False,
            extension_specs=profile.extension_specs,
        )
    if isinstance(profile, CodingProfile):
        return _ProfileSelection(
            capabilities=frozenset(),
            builtin_tools=True,
            caller_tools=profile.extra_tools,
            base_prompt=profile.system_prompt or build_static_system_prompt(),
            dynamic_prompt_enabled=profile.system_prompt is None,
            extension_specs=profile.extension_specs,
        )
    if isinstance(profile, FullProfile):
        return _ProfileSelection(
            capabilities=frozenset(
                {_CAP_SKILL, _CAP_SUBAGENT, _CAP_PLAN},
            ),
            builtin_tools=True,
            caller_tools=profile.extra_tools,
            base_prompt=profile.system_prompt or build_static_system_prompt(),
            dynamic_prompt_enabled=profile.system_prompt is None,
            extension_specs=profile.extension_specs,
        )
    raise TypeError(f"unsupported profile: {type(profile).__name__}")


@dataclass(slots=True)
class _ResolvedBindings:
    """RuntimeBindings + AgentConfig 解析出的构造期值与控制器。"""

    cwd: Path
    provider_factory: ProviderFactory
    hooks_loader: Callable[[], list[Any]]
    dynamic_context_builder: Callable[[list[str]], str]
    renderer_factory: Callable[[], TerminalRenderer]
    notices: NoticeController
    confirmation: ConfirmationController
    permission_controller: PermissionController
    status_sink: SubagentStatusSink | None


def _resolve_bindings(
    config: AgentConfig,
    bindings: RuntimeBindings,
    selection: _ProfileSelection,
) -> _ResolvedBindings:
    cwd = Path.cwd()
    interaction = bindings.interaction
    notices = NoticeController(
        print_info=interaction.print_info or _noop_print,
        print_error=interaction.print_error or _noop_print,
    )
    confirmation = ConfirmationController(
        permission=PermissionController(PermissionState(mode=config.permission_mode)),
        terminal_output=config.terminal_output,
        print_confirmation=interaction.print_confirmation or _noop_print,
        confirm_fn=interaction.confirm_fn,
    )
    status_sink = None
    if selection.capabilities & {_CAP_SUBAGENT, _CAP_SKILL}:
        status_sink = SubagentStatusSink(
            terminal_output=config.terminal_output,
            start=interaction.print_sub_agent_start or _noop_status,
            end=interaction.print_sub_agent_end or _noop_status,
        )
    return _ResolvedBindings(
        cwd=cwd,
        provider_factory=bindings.provider.provider_factory or create_provider,
        hooks_loader=bindings.tool.pre_tool_use_hooks_loader or load_pre_tool_use_hooks,
        dynamic_context_builder=(
            interaction.dynamic_system_context_builder or build_dynamic_system_context
        ),
        renderer_factory=interaction.terminal_renderer_factory or TerminalRenderer,
        notices=notices,
        confirmation=confirmation,
        permission_controller=confirmation.permission,
        status_sink=status_sink,
    )


def _build_foundation(
    selection: _ProfileSelection,
    config: AgentConfig,
    bindings: RuntimeBindings,
) -> _FoundationGraph:
    resolved = _resolve_bindings(config, bindings, selection)
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
    session_repository = bindings.session.session_repository or SessionRepository()
    read_file_state: dict[str, float] = {}

    created_own_registry = bindings.tool.tool_registry is None
    if not created_own_registry and selection.caller_tools:
        raise ValueError("tool_registry cannot be combined with profile tools")
    tool_registry = bindings.tool.tool_registry or ToolRegistry()
    if created_own_registry:
        for tool in selection.caller_tools:
            tool_registry.register(tool)
        if selection.builtin_tools:
            backend = bindings.tool.command_backend or LocalCommandExecutionBackend()
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
        bindings=bindings,
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


def _build_provider_state(config: AgentConfig) -> ProviderState:
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
    return ProviderState(
        model=config.model,
        provider_kind=initial_provider_kind,
        api_key=initial_api_key,
        openai_base_url=config.api_base,
        anthropic_base_url=config.anthropic_base_url,
        thinking_enabled=config.thinking,
        thinking_level=initial_thinking_level,
    )


def _build_identity_port(
    foundation: _FoundationGraph,
    *,
    api_configured: Callable[[], bool],
) -> RuntimeIdentityPort:
    return RuntimeIdentityPort(
        terminal_output=foundation.confirmation.terminal_output,
        api_configured=api_configured,
        terminal_renderer_factory=foundation.renderer_factory,
        notices=foundation.notices,
    )


def _build_capability_graph(
    foundation: _FoundationGraph,
    identity_port: RuntimeIdentityPort,
    selection: _ProfileSelection,
    *,
    child_config: Callable[[], ChildAgentConfig],
) -> _CapabilityGraph:
    capabilities = selection.capabilities

    capability_registry = CapabilityRegistry()
    if selection.builtin_tools:
        capability_registry.register(create_agent_state_capability())
        capability_registry.register(create_git_status_capability())

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
    *,
    provider_hosts: frozenset[str] = frozenset(),
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
    tool_bindings = foundation.bindings.tool
    workspace_snapshot = None
    if tool_bindings.enable_workspace_snapshot:
        workspace_snapshot = tool_bindings.workspace_snapshot or WorkspaceSnapshot(
            foundation.cwd
        )
    secret_store = None
    if tool_bindings.enable_secret_boundary:
        secret_store = tool_bindings.secret_store or load_secret_store(
            workspace=foundation.cwd,
            key_file=Path.home() / ".lion_code" / "sanitizer.key",
        )
    audit_log = None
    if tool_bindings.enable_audit:
        audit_log = tool_bindings.audit_log or ExecutionAuditLog(
            Path.home() / ".lion_code" / "execution.audit",
            store=secret_store,
        )
    egress_whitelist = None
    if tool_bindings.enable_egress_guard:
        egress_whitelist = (
            tool_bindings.egress_whitelist
            or EgressWhitelist.from_sources(
                home=Path.home(),
                cwd=foundation.cwd,
                provider_hosts=provider_hosts,
            )
        )

    def record_audit(tool, arguments, result) -> None:
        if audit_log is not None:
            audit_log.record_tool(tool, arguments, result)

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
        audit_fn=record_audit if audit_log is not None else None,
        workspace_snapshot=workspace_snapshot,
        audit_log=audit_log,
    )
    permission_policy = PermissionPolicy(cwd=foundation.cwd)
    result_store = ResultStore()
    middleware: list[ToolMiddleware] = [
        CancellationMiddleware(),
    ]
    if workspace_snapshot is not None:
        middleware.append(WorkspaceSnapshotMiddleware(workspace_snapshot))
    # post 链首位：redact 必须先于 ResultStore 落盘与审计记录
    if secret_store is not None:
        middleware.append(OutputSanitizerMiddleware(secret_store))
    middleware.extend(
        [
            PreToolHookMiddleware(),
            PermissionMiddleware(
                permission_policy,
                foundation.permission_controller,
            ),
            # 出口判定在权限之后、执行之前
            *(
                [EgressGuardMiddleware(egress_whitelist, secret_store)]
                if egress_whitelist is not None
                else []
            ),
            ReadFreshnessMiddleware(),
            ResultPolicyMiddleware(result_store),
            AuditMiddleware(),
        ]
    )
    tool_runtime = ToolRuntime(
        foundation.tool_registry,
        tool_context,
        middleware,
    )
    context_layers = capability_registry.context_layers
    context_manager = foundation.bindings.session.context_manager
    if context_manager is None:
        context_manager = ContextManager(
            is_snippable_tool=lambda name: _is_snippable_tool(
                foundation.tool_registry, name
            ),
            # 只捕获构造完成后的不可变层快照，避免 ContextRuntime 反向持有
            # CapabilityRegistry；动态状态由各 Layer 在 render 时读取。
            context_layers=lambda: context_layers,
        )
    return _ToolingGraph(
        prompt_composer=prompt_composer,
        tool_context=tool_context,
        permission_policy=permission_policy,
        result_store=result_store,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
    )


def _child_config(
    provider_projection: ProviderConfigurationProjection,
    identity_port: RuntimeIdentityPort,
) -> ChildAgentConfig:
    kwargs = provider_projection.child_api_kwargs()
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
