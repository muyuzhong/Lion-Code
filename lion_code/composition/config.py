"""Agent 的用户配置与外部依赖入口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..capabilities.types import CapabilitySpec
    from ..context import ContextCompactor, ContextManager, ModelLimitsResolver
    from ..core.provider import ModelProvider
    from ..permission_state import PermissionMode
    from ..project_identity import ProjectIdentity
    from ..session_memory import SessionMemoryRepository
    from ..session_runtime import SessionRepository
    from ..tooling import ToolRegistry
    from ..tools import ToolDef


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """只描述用户可见的 Agent 运行配置，不保存运行时对象。"""

    model: str = "claude-opus-4-6"
    api_base: str | None = None
    anthropic_base_url: str | None = None
    api_key: str | None = None
    permission_mode: PermissionMode = "default"
    thinking: bool = False
    max_cost_usd: float | None = None
    max_turns: int | None = None
    custom_system_prompt: str | None = None
    custom_tools: tuple[ToolDef, ...] | None = None
    is_sub_agent: bool = False
    terminal_output: bool = True

    def __post_init__(self) -> None:
        if self.custom_tools is not None:
            object.__setattr__(self, "custom_tools", tuple(self.custom_tools))


@dataclass(frozen=True, slots=True)
class AgentDependencies:
    """表示外部注入对象、工厂和测试 seam，不承担运行时状态所有权。"""

    confirm_fn: Callable[[str], Awaitable[bool]] | None = None
    tool_registry: ToolRegistry | None = None
    session_repository: SessionRepository | None = None
    session_memory_repository: SessionMemoryRepository | None = None
    context_manager: ContextManager | None = None
    context_compactor: ContextCompactor | None = None
    model_limits_resolver: ModelLimitsResolver | None = None
    provider: ModelProvider | None = None
    provider_factory: Callable[..., ModelProvider] | None = None
    pre_tool_use_hooks_loader: Callable[[], list[Any]] | None = None
    project_identity_resolver: Callable[[Any], ProjectIdentity] | None = None
    project_context_loader: Callable[[Any, ProjectIdentity], Sequence[Any]] | None = (
        None
    )
    dynamic_system_context_builder: Callable[[Sequence[str]], str] | None = None
    terminal_renderer_factory: Callable[[], Any] | None = None
    print_info: Callable[[str], None] | None = None
    print_error: Callable[[str], None] | None = None
    print_confirmation: Callable[[str], None] | None = None
    print_sub_agent_start: Callable[[str, str], None] | None = None
    print_sub_agent_end: Callable[[str, str], None] | None = None
    extra_capabilities: tuple[CapabilitySpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_capabilities", tuple(self.extra_capabilities))
