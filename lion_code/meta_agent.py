"""Zero-extension MetaAgent facade over Lion's shared Kernel and Harness."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from .agent_runtime import AgentRunResult, AgentRuntimeCoordinator
from .capabilities.registry import CapabilityRegistry
from .composition import AgentConfig, AgentDependencies, build_agent_composition
from .context import ContextCompactor, ContextManager, ModelLimitsResolver
from .core import AgentMessage, EventListener, QueueSnapshot
from .core.provider import ModelProvider
from .permission_state import PermissionMode
from .provider_manager import ProviderFactory, ProviderManager
from .providers.thinking import ThinkingLevel
from .session_identity import SessionIdentityState
from .session_runtime import SessionRepository
from .tooling import LionTool, ToolRegistry
from .usage import BudgetPolicy, UsageLedger, UsageSnapshot

_META_SYSTEM_PROMPT = "You are a helpful assistant."


class MetaAgent:
    """只暴露通用对话、会话、Provider、事件与用量能力的 facade。"""

    __slots__ = (
        "_budget",
        "_capability_registry",
        "_closed",
        "_provider_manager",
        "_runtime",
        "_session_state",
        "_usage",
    )

    def __init__(
        self,
        *,
        runtime: AgentRuntimeCoordinator,
        provider_manager: ProviderManager,
        session_state: SessionIdentityState,
        usage: UsageLedger,
        budget: BudgetPolicy,
        capability_registry: CapabilityRegistry,
    ) -> None:
        self._runtime = runtime
        self._provider_manager = provider_manager
        self._session_state = session_state
        self._usage = usage
        self._budget = budget
        self._capability_registry = capability_registry
        self._closed = False

    async def run(
        self,
        prompt: str,
        *,
        timeout: float | None = None,
    ) -> AgentRunResult:
        return await self._runtime.run(prompt, timeout=timeout)

    async def chat(self, prompt: str) -> None:
        await self._runtime.chat(prompt)

    async def prompt(self, content: str) -> None:
        await self.chat(content)

    async def continue_(self) -> None:
        await self._runtime.core_runtime.continue_()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return self._runtime.core_runtime.messages

    @property
    def conversation(self) -> tuple[AgentMessage, ...]:
        return self.messages

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        return self._runtime.core_runtime.subscribe(listener)

    def steer(self, content: str) -> QueueSnapshot:
        return self._runtime.core_runtime.steer(content)

    def follow_up(self, content: str) -> QueueSnapshot:
        return self._runtime.core_runtime.follow_up(content)

    def cancel(self) -> None:
        self._runtime.abort()

    @property
    def cancelled(self) -> bool:
        return self._runtime.execution.cancelled

    async def compact(self) -> None:
        await self._runtime.compact()

    @property
    def session_id(self) -> str:
        return self._session_state.id

    async def new_session(self) -> None:
        await self._runtime.clear_history()

    async def restore(self, session_id: str) -> bool:
        return await self._runtime.restore_core_session(session_id)

    @property
    def provider(self) -> ModelProvider:
        return self._runtime.core_runtime.provider

    @property
    def model(self) -> str:
        return self._provider_manager.model

    def provider_config(self) -> dict[str, bool | str]:
        return self._provider_manager.get_api_config()

    def configure_provider(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None:
        self._provider_manager.configure(
            model=model,
            api_key=api_key,
            api_base=api_base,
            anthropic_base_url=anthropic_base_url,
            use_openai=use_openai,
        )

    @property
    def thinking(self) -> bool:
        return self._provider_manager.thinking

    def set_thinking(self, enabled: bool) -> str:
        return self._provider_manager.set_thinking(enabled)

    @property
    def thinking_level(self) -> ThinkingLevel:
        return self._provider_manager.thinking_level

    @property
    def available_thinking_levels(self) -> tuple[ThinkingLevel, ...]:
        return self._provider_manager.available_thinking_levels

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        return self._provider_manager.set_thinking_level(level)

    def cycle_thinking_level(self) -> ThinkingLevel:
        return self._provider_manager.cycle_thinking_level()

    @property
    def usage(self) -> UsageSnapshot:
        return self._usage.snapshot()

    @property
    def budget(self) -> BudgetPolicy:
        return self._budget

    async def close(self) -> None:
        if self._closed:
            return
        await self._runtime.close()
        self._closed = True


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

    tool_registry = ToolRegistry()
    for tool in tools:
        tool_registry.register(tool)
    composition = build_agent_composition(
        AgentConfig(
            model=model,
            permission_mode=permission_mode,
            custom_system_prompt=system_prompt or _META_SYSTEM_PROMPT,
            thinking=thinking,
            max_cost_usd=max_cost_usd,
            max_turns=max_turns,
            terminal_output=False,
            mcp_enabled=False,
        ),
        AgentDependencies(
            confirm_fn=confirm_fn,
            tool_registry=tool_registry,
            session_repository=session_repository,
            context_manager=context_manager,
            context_compactor=context_compactor,
            model_limits_resolver=model_limits_resolver,
            provider=provider,
            provider_factory=provider_factory,
            pre_tool_use_hooks_loader=lambda: [],
        ),
        capabilities=frozenset(),
    )
    return MetaAgent(
        runtime=composition.runtime_coordinator,
        provider_manager=composition.provider_manager,
        session_state=composition.session_state,
        usage=composition.usage,
        budget=composition.budget,
        capability_registry=composition.capability_registry,
    )


__all__ = ["MetaAgent", "build_meta_agent"]
