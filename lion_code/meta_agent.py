"""Zero-extension MetaAgent facade over Lion's shared Kernel and Harness."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from .composition import (
    NEUTRAL_SYSTEM_PROMPT,
    AgentConfig,
    CodingProfile,
    InteractionBindings,
    MinimalProfile,
    Profile,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
    ToolBindings,
    build_agent_composition,
)
from .composition.agent_builder import AgentComposition
from .context import ContextCompactor, ContextManager, ModelLimitsResolver
from .core import AgentMessage, EventListener, QueueSnapshot
from .core.provider import ModelProvider
from .hooks import load_pre_tool_use_hooks
from .permission_state import PermissionMode
from .providers.thinking import ThinkingLevel
from .runtime.agent import AgentRunResult, AgentRuntime
from .runtime.conversation import ConversationRuntime
from .runtime.provider import ProviderController, ProviderFactory
from .runtime.session import SessionRuntime
from .session_runtime import SessionRepository
from .tooling import (
    CommandExecutionBackend,
    LionTool,
    LocalCommandExecutionBackend,
    ToolRegistry,
)
from .usage import BudgetPolicy, UsageLedger, UsageSnapshot

_META_SYSTEM_PROMPT = NEUTRAL_SYSTEM_PROMPT


class MetaAgent:
    """只暴露通用对话、会话、Provider、事件与用量能力的 facade。

    facade 是 Runtime 平面与 Provider 平面之间唯一的显式协调点：
    new_session 把当前 Provider 视图传给 AgentRuntime，restore 先由
    SessionRuntime 产出不可变快照、再命令 ProviderController 恢复配置、
    最后交给 AgentRuntime 回放。
    """

    __slots__ = (
        "_agent_runtime",
        "_budget",
        "_closed",
        "_conversation",
        "_permission_mode",
        "_provider_controller",
        "_session",
        "_usage",
    )

    def __init__(
        self,
        *,
        agent_runtime: AgentRuntime,
        provider_controller: ProviderController,
        conversation: ConversationRuntime,
        session: SessionRuntime,
        usage: UsageLedger,
        budget: BudgetPolicy,
        permission_mode: PermissionMode,
    ) -> None:
        self._agent_runtime = agent_runtime
        self._provider_controller = provider_controller
        self._conversation = conversation
        self._session = session
        self._usage = usage
        self._budget = budget
        self._permission_mode = permission_mode
        self._closed = False

    async def run(
        self,
        prompt: str,
        *,
        timeout: float | None = None,
    ) -> AgentRunResult:
        return await self._agent_runtime.run(prompt, timeout=timeout)

    async def run_once(self, prompt: str) -> dict:
        """执行单轮 fork 语义；供 SubAgent/Skill child runtime 使用。"""
        return await self._agent_runtime.run_once(prompt)

    async def chat(self, prompt: str) -> None:
        await self._agent_runtime.chat(prompt)

    async def prompt(self, content: str) -> None:
        await self.chat(content)

    async def continue_(self) -> None:
        await self._conversation.continue_()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return self._conversation.messages

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        return self._conversation.subscribe(listener)

    def steer(self, content: str) -> QueueSnapshot:
        return self._conversation.steer(content)

    def follow_up(self, content: str) -> QueueSnapshot:
        return self._conversation.follow_up(content)

    def cancel(self) -> None:
        self._agent_runtime.abort()

    @property
    def cancelled(self) -> bool:
        return self._agent_runtime.execution.cancelled

    async def compact(self) -> None:
        await self._agent_runtime.compact()

    @property
    def session_id(self) -> str:
        return self._session.state.id

    async def new_session(self) -> None:
        """结束当前会话并创建新 Session；Recorder 初始配置取自当前 Provider 视图。"""
        view = self._provider_controller.view
        await self._agent_runtime.new_session(
            model=view.model,
            thinking_level=view.thinking_level,
        )

    async def _restore_core_session(self, session_id: str) -> bool:
        """显式跨 Owner 编排：load → restore_configuration → AgentRuntime.restore。"""
        state = await self._session.load(session_id)
        if state is None:
            return False
        self._provider_controller.restore_configuration(
            model=state.model,
            thinking_level=state.thinking_level,
        )
        return await self._agent_runtime.restore(state)

    async def restore(self, session_id: str) -> bool:
        return await self._restore_core_session(session_id)

    @property
    def provider(self) -> ModelProvider:
        return self._conversation.provider

    @property
    def model(self) -> str:
        return self._provider_controller.model

    @property
    def permission_mode(self) -> PermissionMode:
        """构造时确定的权限模式只读投影。"""
        return self._permission_mode

    def provider_config(self) -> dict[str, bool | str]:
        return self._provider_controller.get_api_config()

    def configure_provider(self, **kwargs: Any) -> None:
        self._provider_controller.configure(**kwargs)

    @property
    def thinking(self) -> bool:
        return self._provider_controller.thinking

    @property
    def thinking_level(self) -> ThinkingLevel:
        return self._provider_controller.thinking_level

    @property
    def available_thinking_levels(self) -> tuple[ThinkingLevel, ...]:
        return self._provider_controller.available_thinking_levels

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        return self._provider_controller.set_thinking_level(level)

    def cycle_thinking_level(self) -> ThinkingLevel:
        return self._provider_controller.cycle_thinking_level()

    @property
    def usage(self) -> UsageSnapshot:
        return self._usage.snapshot()

    @property
    def budget(self) -> BudgetPolicy:
        return self._budget

    async def close(self) -> None:
        if self._closed:
            return
        await self._agent_runtime.close()
        self._closed = True


def _build_meta_facade(
    composition: AgentComposition,
    permission_mode: PermissionMode,
) -> MetaAgent:
    runtime = composition.runtime
    return MetaAgent(
        agent_runtime=runtime.agent,
        provider_controller=runtime.provider_controller,
        conversation=runtime.conversation,
        session=runtime.session,
        usage=runtime.usage,
        budget=runtime.budget,
        permission_mode=permission_mode,
    )


def build_profile_agent(
    profile: Profile,
    *,
    config: AgentConfig,
    bindings: RuntimeBindings,
) -> MetaAgent:
    """从任一不可变 Profile 构造只暴露通用 API 的 MetaAgent。

    三轴输入只经此转发进 Composition Root，facade 不做任何组合决策。
    """

    return _build_meta_facade(
        build_agent_composition(profile, config=config, bindings=bindings),
        config.permission_mode,
    )


def build_meta_agent(
    *,
    provider: ModelProvider,
    tools: Sequence[LionTool] = (),
    model: str = "meta",
    permission_mode: PermissionMode = "default",
    system_prompt: str = _META_SYSTEM_PROMPT,
    thinking: bool = False,
    max_cost_usd: float | None = None,
    max_turns: int | None = None,
    confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
    session_repository: SessionRepository | None = None,
    context_manager: ContextManager | None = None,
    context_compactor: ContextCompactor | None = None,
    model_limits_resolver: ModelLimitsResolver | None = None,
    provider_factory: ProviderFactory | None = None,
) -> MetaAgent:
    """构建固定空 CapabilityRegistry、只注册调用方工具的 MetaAgent。"""

    profile = MinimalProfile(
        tools=tuple(tools),
        system_prompt=system_prompt or _META_SYSTEM_PROMPT,
    )
    config = AgentConfig(
        model=model,
        permission_mode=permission_mode,
        thinking=thinking,
        max_cost_usd=max_cost_usd,
        max_turns=max_turns,
        terminal_output=False,
    )
    bindings = RuntimeBindings(
        provider=ProviderBindings(
            provider=provider,
            provider_factory=provider_factory,
            model_limits_resolver=model_limits_resolver,
        ),
        session=SessionBindings(
            session_repository=session_repository,
            context_manager=context_manager,
            context_compactor=context_compactor,
        ),
        tool=ToolBindings(pre_tool_use_hooks_loader=lambda: []),
        interaction=InteractionBindings(confirm_fn=confirm_fn),
    )
    return build_profile_agent(profile, config=config, bindings=bindings)


def build_coding_agent(
    *,
    model: str = "claude-opus-4-6",
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    api_key: str | None = None,
    permission_mode: PermissionMode = "default",
    thinking: bool = False,
    max_cost_usd: float | None = None,
    max_turns: int | None = None,
    terminal_output: bool = True,
    is_sub_agent: bool = False,
    system_prompt: str | None = None,
    command_backend: CommandExecutionBackend | None = None,
    extra_tools: Sequence[LionTool] = (),
    tool_registry: ToolRegistry | None = None,
) -> MetaAgent:
    """构建 Coding 产品形态：backend 绑定的 Coding 工具与 Meta facade。

    子 Agent/Skill child graph 也走本入口；调用方可注入 caller-owned
    registry view 与 fake command backend 隔离副作用。
    """
    profile = CodingProfile(
        extra_tools=tuple(extra_tools),
        system_prompt=system_prompt,
    )
    config = AgentConfig(
        model=model,
        api_base=api_base,
        anthropic_base_url=anthropic_base_url,
        api_key=api_key,
        permission_mode=permission_mode,
        thinking=thinking,
        max_cost_usd=max_cost_usd,
        max_turns=max_turns,
        is_sub_agent=is_sub_agent,
        terminal_output=terminal_output,
    )
    bindings = RuntimeBindings(
        tool=ToolBindings(
            tool_registry=tool_registry,
            command_backend=command_backend or LocalCommandExecutionBackend(),
            pre_tool_use_hooks_loader=load_pre_tool_use_hooks,
        ),
    )
    return build_profile_agent(profile, config=config, bindings=bindings)


__all__ = [
    "MetaAgent",
    "build_coding_agent",
    "build_meta_agent",
    "build_profile_agent",
]
