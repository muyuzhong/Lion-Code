"""CapabilityRegistry: aggregates Capability contributions after dependency resolution.

The registry is **not** a service locator or dependency-injection container.
It only:

- Accepts ``CapabilitySpec`` registrations.
- Validates name uniqueness.
- Resolves explicit ``requires`` dependencies (stable topological sort).
- Exposes aggregated extension slots in resolved order.

It must not import ``Agent``, create ``Provider`` objects, create ``Session``
objects, modify ``Permission``, or hold runtime state beyond the registry
itself.
"""

from __future__ import annotations

from .types import (
    AsyncCloseable,
    CapabilitySpec,
    ProjectionLayer,
    PromptLayer,
    SessionParticipant,
    ToolSource,
    TurnParticipant,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CapabilityError(Exception):
    """Base error for Capability registry failures."""


class DuplicateCapabilityError(CapabilityError):
    """A Capability with this name is already registered."""


class MissingDependencyError(CapabilityError):
    """A Capability requires a name that is not registered."""


class CircularDependencyError(CapabilityError):
    """Capability dependencies form a cycle."""


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------


def _topological_sort(
    specs: dict[str, CapabilitySpec],
) -> tuple[str, ...]:
    """Return capability names in dependency-resolved order.

    Raises ``MissingDependencyError`` for unknown ``requires``.
    Raises ``CircularDependencyError`` for dependency cycles.

    The sort is *stable*: capabilities with no inter-dependencies preserve
    their registration order.  This is achieved by using Kahn's algorithm
    with a ready-queue that is re-sorted by registration index whenever new
    nodes become unblocked.
    """
    registration_order = list(specs.keys())
    order_index = {name: i for i, name in enumerate(registration_order)}

    # Validate all requires reference registered capabilities.
    for name, spec in specs.items():
        for dep in spec.requires:
            if dep not in specs:
                raise MissingDependencyError(
                    f"Capability '{name}' requires unknown capability '{dep}'"
                )

    # in_degree[name] = number of unsatisfied requires.
    in_degree: dict[str, int] = {
        name: len(spec.requires) for name, spec in specs.items()
    }
    # dependents[dep] = list of capabilities that require *dep*.
    dependents: dict[str, list[str]] = {name: [] for name in specs}
    for name, spec in specs.items():
        for dep in spec.requires:
            dependents[dep].append(name)

    # Ready queue: capabilities with no unsatisfied requires, in
    # registration order.
    ready = sorted(
        [name for name in registration_order if in_degree[name] == 0],
        key=lambda n: order_index[n],
    )
    result: list[str] = []

    while ready:
        current = ready.pop(0)
        result.append(current)
        newly_ready: list[str] = []
        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                newly_ready.append(dependent)
        if newly_ready:
            ready.extend(newly_ready)
            ready.sort(key=lambda n: order_index[n])

    if len(result) != len(specs):
        unresolved = sorted(set(specs) - set(result))
        raise CircularDependencyError(
            f"Circular dependency detected among capabilities: {unresolved}"
        )

    return tuple(result)


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------


class CapabilityRegistry:
    """Organizes ``CapabilitySpec`` contributions with dependency-ordered aggregation.

    The registry is NOT a service locator or DI container.  It only accepts
    ``CapabilitySpec`` registrations, resolves dependency ordering, and
    exposes aggregated extension slots in resolved order.

    It must not import ``Agent``, create ``Provider`` objects, create
    ``Session`` objects, modify ``Permission``, or hold runtime state beyond
    the registry itself.
    """

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        self._order: tuple[str, ...] | None = None

    # -- registration --------------------------------------------------

    def register(self, spec: CapabilitySpec) -> None:
        """Register a ``CapabilitySpec``.

        Names must be unique.  Registration invalidates the cached
        dependency order; call :meth:`resolve` (or access any aggregated
        property) to re-resolve.
        """
        if spec.name in self._specs:
            raise DuplicateCapabilityError(
                f"Capability '{spec.name}' is already registered"
            )
        self._specs[spec.name] = spec
        self._order = None

    # -- resolution ----------------------------------------------------

    def resolve(self) -> tuple[str, ...]:
        """Resolve dependencies and compute the topological order.

        Returns the ordered tuple of capability names.  Subsequent calls
        return the cached order until a new ``register`` invalidates it.

        Raises ``MissingDependencyError`` for unknown ``requires``.
        Raises ``CircularDependencyError`` for dependency cycles.
        """
        if self._order is None:
            self._order = _topological_sort(self._specs)
        return self._order

    def _ensure_resolved(self) -> tuple[str, ...]:
        """Lazily resolve if the cached order has been invalidated."""
        if self._order is None:
            self._order = _topological_sort(self._specs)
        return self._order

    # -- queries -------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        """All registered capability names in registration order."""
        return tuple(self._specs)

    def get(self, name: str) -> CapabilitySpec | None:
        """Return the spec for *name*, or ``None`` if not registered."""
        return self._specs.get(name)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    # -- aggregated extension slots -----------------------------------

    @property
    def tool_sources(self) -> tuple[ToolSource, ...]:
        """All tool sources in dependency-resolved order."""
        order = self._ensure_resolved()
        return tuple(
            source for name in order for source in self._specs[name].tool_sources
        )

    @property
    def prompt_layers(self) -> tuple[PromptLayer, ...]:
        """All prompt layers in dependency-resolved order."""
        order = self._ensure_resolved()
        return tuple(
            layer for name in order for layer in self._specs[name].prompt_layers
        )

    @property
    def projection_layers(self) -> tuple[ProjectionLayer, ...]:
        """All per-request projection layers in dependency-resolved order."""
        order = self._ensure_resolved()
        return tuple(
            layer for name in order for layer in self._specs[name].projection_layers
        )

    @property
    def turn_participants(self) -> tuple[TurnParticipant, ...]:
        """All turn participants in dependency-resolved order."""
        order = self._ensure_resolved()
        return tuple(
            participant
            for name in order
            for participant in self._specs[name].turn_participants
        )

    @property
    def session_participants(self) -> tuple[SessionParticipant, ...]:
        """All session participants in dependency-resolved order."""
        order = self._ensure_resolved()
        return tuple(
            participant
            for name in order
            for participant in self._specs[name].session_participants
        )

    @property
    def resources(self) -> tuple[AsyncCloseable, ...]:
        """All closeable resources in dependency-resolved order."""
        order = self._ensure_resolved()
        return tuple(
            resource for name in order for resource in self._specs[name].resources
        )

    # -- lifecycle -----------------------------------------------------

    async def close_all(self) -> None:
        """Close all resources in reverse dependency order.

        Resources within a single capability are closed in reverse
        declaration order (last declared → first closed).

        All resources are attempted even if one raises.  If any raise,
        the first exception is re-raised after all closures have been
        attempted.
        """
        order = self._ensure_resolved()
        errors: list[Exception] = []
        for name in reversed(order):
            spec = self._specs[name]
            for resource in reversed(spec.resources):
                try:
                    await resource.close()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
        if errors:
            raise errors[0]
