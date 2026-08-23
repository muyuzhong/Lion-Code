"""Extension slot protocols and the immutable ``CapabilitySpec``.

Each extension slot is a narrow ``Protocol`` that a capability implements to
contribute a specific kind of extension to the Agent.  The protocols are
intentionally minimal—no ``Agent``, no ``AgentHarness``, no god-object
context.  A capability receives only the narrow dependency it truly needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from lion_code.context.types import ContextView
    from lion_code.tooling.types import LionTool


# ---------------------------------------------------------------------------
# Extension slot protocols
# ---------------------------------------------------------------------------


class AsyncCloseable(Protocol):
    """A resource that must be asynchronously closed when its Capability is removed.

    Capabilities that own long-lived resources (connections, file handles,
    background tasks) should expose them through this protocol so the
    registry can close them in the correct order.
    """

    async def close(self) -> None: ...


class ToolSource(Protocol):
    """Provides tools to the Agent's ``ToolRegistry``.

    The Agent composition root calls ``tools()`` during setup and registers
    each returned ``LionTool`` with the registry.  The tool source must not
    retain a reference to ``Agent`` or ``ToolRegistry``.
    """

    def tools(self) -> Sequence[LionTool]: ...


class PromptLayer(Protocol):
    """Contribute a fresh prompt fragment without mutating runtime state."""

    @property
    def layer_id(self) -> str: ...

    def render(self) -> str: ...


class ContextLayer(Protocol):
    """向 prepared context 提供每次请求的临时状态。

    ``PromptLayer`` 贡献相对稳定的 System Prompt 内容；``ContextLayer``
    在每次 Provider 请求前渲染当前状态，结果只保留在本次 prepared
    context 中，不得进入 canonical conversation history 或持久化 Session。
    """

    @property
    def layer_id(self) -> str: ...

    def render(self, view: ContextView) -> str: ...


class QueryContextLayer(Protocol):
    """按最新 user query 渲染 prepared-only 查询投影。

    与 ``ContextLayer`` 同属 prepared-context 尾部临时投影，但输入多一个
    由 ContextManager 从当前 prepared messages 提取的最新 user query：
    用于本地确定性检索（如 semantic memory 自动召回），不得调用
    Provider、不得写 canonical history 或任何持久化状态。
    """

    @property
    def layer_id(self) -> str: ...

    def render(self, query: str, view: ContextView) -> str: ...


class SessionParticipant(Protocol):
    """Participates in session lifecycle transitions.

    ``on_new_session`` is called when a new session begins (``/clear``);
    ``on_restore_session`` is called when an existing session is restored.
    Only capabilities that need session-scoped initialization should
    implement this protocol.
    """

    async def on_new_session(self) -> None: ...

    async def on_restore_session(self) -> None: ...


# ---------------------------------------------------------------------------
# CapabilitySpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Immutable description of a Capability's contributions.

    A Capability declares what it provides through extension slots.  The
    ``CapabilityRegistry`` aggregates these contributions in registration
    order.

    Parameters
    ----------
    name:
        Unique capability identifier (e.g. ``"browser"``, ``"sandbox"``).
    tool_sources:
        ``ToolSource`` instances whose tools should be registered.
    prompt_layers:
        ``PromptLayer`` instances whose fragments should be composed.
    session_participants:
        ``SessionParticipant`` instances that need session lifecycle hooks.
    resources:
        ``AsyncCloseable`` instances that must be closed on shutdown.
    context_layer:
        An optional per-request context projection.  Its rendered output is
        transient and never enters canonical history or session persistence.
    query_context_layer:
        An optional query-aware per-request projection.  Same transient
        contract as ``context_layer``, additionally receiving the latest
        user query from the prepared messages.
    """

    name: str
    tool_sources: tuple[ToolSource, ...] = ()
    prompt_layers: tuple[PromptLayer, ...] = ()
    session_participants: tuple[SessionParticipant, ...] = ()
    resources: tuple[AsyncCloseable, ...] = ()
    context_layer: ContextLayer | None = None
    query_context_layer: QueryContextLayer | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_sources", tuple(self.tool_sources))
        object.__setattr__(self, "prompt_layers", tuple(self.prompt_layers))
        object.__setattr__(
            self, "session_participants", tuple(self.session_participants)
        )
        object.__setattr__(self, "resources", tuple(self.resources))
        if not self.name:
            raise ValueError("CapabilitySpec.name must be a non-empty string")
