"""RuntimeBindings：按职责组织的 concrete 实现绑定。

三轴分离中本模块承载 WITH WHAT：Profile 决定组装哪一种产品形态，
AgentConfig 决定怎样运行，RuntimeBindings 决定使用哪些具体实现。
四组 binding 只携带外部实现引用（协议对象、工厂、回调），不拥有
运行时状态，只在 Composition Root 被读取一次。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..context import ContextCompactor, ContextManager, ModelLimitsResolver
    from ..core.provider import ModelProvider
    from ..session_runtime import SessionRepository
    from ..tooling import ToolRegistry
    from ..tooling.execution import CommandExecutionBackend


@dataclass(frozen=True, slots=True)
class ProviderBindings:
    """模型 Provider 基础设施绑定。"""

    provider: ModelProvider | None = None
    provider_factory: Callable[..., ModelProvider] | None = None
    model_limits_resolver: ModelLimitsResolver | None = None


@dataclass(frozen=True, slots=True)
class SessionBindings:
    """会话与上下文基础设施绑定。"""

    session_repository: SessionRepository | None = None
    context_manager: ContextManager | None = None
    context_compactor: ContextCompactor | None = None


@dataclass(frozen=True, slots=True)
class ToolBindings:
    """工具注册与命令执行绑定。

    ``command_backend`` 是 concrete binding，不属于任何 Profile：
    Coding/Full 产品形态读取它构造内置工具，缺省落到本地实现。
    """

    tool_registry: ToolRegistry | None = None
    command_backend: CommandExecutionBackend | None = None
    pre_tool_use_hooks_loader: Callable[[], list[Any]] | None = None


@dataclass(frozen=True, slots=True)
class InteractionBindings:
    """交互呈现与测试 seam 回调。"""

    confirm_fn: Callable[[str], Awaitable[bool]] | None = None
    dynamic_system_context_builder: Callable[[Sequence[str]], str] | None = None
    terminal_renderer_factory: Callable[[], Any] | None = None
    print_info: Callable[[str], None] | None = None
    print_error: Callable[[str], None] | None = None
    print_confirmation: Callable[[str], None] | None = None
    print_sub_agent_start: Callable[[str, str], None] | None = None
    print_sub_agent_end: Callable[[str, str], None] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeBindings:
    """Concrete implementation bindings，按 Provider/Session/Tool/Interaction 四组组织。

    不是依赖大杂烩：字段按职责分组，且不承担运行时状态所有权——
    Composition Root 读取后产生的全部 mutable state 归 AgentComposition 各 owner。
    """

    provider: ProviderBindings = field(default_factory=ProviderBindings)
    session: SessionBindings = field(default_factory=SessionBindings)
    tool: ToolBindings = field(default_factory=ToolBindings)
    interaction: InteractionBindings = field(default_factory=InteractionBindings)


__all__ = [
    "InteractionBindings",
    "ProviderBindings",
    "RuntimeBindings",
    "SessionBindings",
    "ToolBindings",
]
