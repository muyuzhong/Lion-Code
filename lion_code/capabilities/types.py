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
    from lion_code.core.messages import AgentMessage
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


class ProjectionLayer(Protocol):
    """在不修改 canonical history 的前提下贡献单次 Provider 投影。"""

    @property
    def layer_id(self) -> str: ...

    def project(
        self,
        messages: Sequence[AgentMessage],
        *,
        max_tokens: int | None,
    ) -> list[AgentMessage]: ...


class TurnParticipant(Protocol):
    """Participates in the per-turn execution lifecycle.

    ``before_turn`` is called before the Provider stream starts; ``after_turn``
    is called after the turn completes (including tool loops).  Only
    capabilities that genuinely need per-turn hooks should implement this
    protocol.
    """

    async def before_turn(self, user_message: str) -> None: ...

    async def after_turn(self) -> None: ...


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
    ``CapabilityRegistry`` aggregates these contributions after resolving
    dependency ordering.

    Parameters
    ----------
    name:
        Unique capability identifier (e.g. ``"browser"``, ``"sandbox"``).
    tool_sources:
        ``ToolSource`` instances whose tools should be registered.
    prompt_layers:
        ``PromptLayer`` instances whose fragments should be composed.
    projection_layers:
        ``ProjectionLayer`` instances that derive a per-request Provider
        projection without changing canonical history.
    turn_participants:
        ``TurnParticipant`` instances that need per-turn hooks.
    session_participants:
        ``SessionParticipant`` instances that need session lifecycle hooks.
    resources:
        ``AsyncCloseable`` instances that must be closed on shutdown.
    requires:
        Names of other capabilities that must be initialized before this one.
        Dependency ordering is explicit—no priority numbers.
    """

    name: str
    tool_sources: tuple[ToolSource, ...] = ()
    prompt_layers: tuple[PromptLayer, ...] = ()
    projection_layers: tuple[ProjectionLayer, ...] = ()
    turn_participants: tuple[TurnParticipant, ...] = ()
    session_participants: tuple[SessionParticipant, ...] = ()
    resources: tuple[AsyncCloseable, ...] = ()
    requires: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_sources", tuple(self.tool_sources))
        object.__setattr__(self, "prompt_layers", tuple(self.prompt_layers))
        object.__setattr__(self, "projection_layers", tuple(self.projection_layers))
        object.__setattr__(self, "turn_participants", tuple(self.turn_participants))
        object.__setattr__(
            self, "session_participants", tuple(self.session_participants)
        )
        object.__setattr__(self, "resources", tuple(self.resources))
        object.__setattr__(self, "requires", frozenset(self.requires))
        if not self.name:
            raise ValueError("CapabilitySpec.name must be a non-empty string")
