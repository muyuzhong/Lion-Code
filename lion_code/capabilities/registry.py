"""CapabilityRegistry: aggregates Capability contributions in registration order.

The registry is **not** a service locator or dependency-injection container.
It only:

- Accepts ``CapabilitySpec`` registrations.
- Validates name uniqueness.
- Exposes aggregated extension slots in registration order.

It must not import ``Agent``, create ``Provider`` objects, create ``Session``
objects, modify ``Permission``, or hold runtime state beyond the registry
itself.
"""

from __future__ import annotations

from .types import (
    AsyncCloseable,
    CapabilitySpec,
    ContextLayer,
    PromptLayer,
    SessionParticipant,
    ToolSource,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuplicateCapabilityError(Exception):
    """A Capability with this name is already registered."""


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------


class CapabilityRegistry:
    """Organizes ``CapabilitySpec`` contributions with ordered aggregation.

    The registry is NOT a service locator or DI container.  It only accepts
    ``CapabilitySpec`` registrations and exposes aggregated extension slots
    in registration order.

    It must not import ``Agent``, create ``Provider`` objects, create
    ``Session`` objects, modify ``Permission``, or hold runtime state beyond
    the registry itself.
    """

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}

    # -- registration --------------------------------------------------

    def register(self, spec: CapabilitySpec) -> None:
        """Register a ``CapabilitySpec``.

        Names must be unique.
        """
        if spec.name in self._specs:
            raise DuplicateCapabilityError(
                f"Capability '{spec.name}' is already registered"
            )
        self._specs[spec.name] = spec

    # -- aggregated extension slots -----------------------------------

    @property
    def tool_sources(self) -> tuple[ToolSource, ...]:
        """All tool sources in registration order."""
        return tuple(
            source for spec in self._specs.values() for source in spec.tool_sources
        )

    @property
    def prompt_layers(self) -> tuple[PromptLayer, ...]:
        """All prompt layers in registration order."""
        return tuple(
            layer for spec in self._specs.values() for layer in spec.prompt_layers
        )

    @property
    def session_participants(self) -> tuple[SessionParticipant, ...]:
        """All session participants in registration order."""
        return tuple(
            participant
            for spec in self._specs.values()
            for participant in spec.session_participants
        )

    @property
    def resources(self) -> tuple[AsyncCloseable, ...]:
        """All closeable resources in registration order."""
        return tuple(
            resource for spec in self._specs.values() for resource in spec.resources
        )

    @property
    def context_layers(self) -> tuple[ContextLayer, ...]:
        """All non-empty context layers in registration order."""
        return tuple(
            spec.context_layer
            for spec in self._specs.values()
            if spec.context_layer is not None
        )

    # -- lifecycle -----------------------------------------------------

    async def close_all(self) -> None:
        """Close all resources in reverse registration order.

        Resources within a single capability are closed in reverse
        declaration order (last declared → first closed).

        All resources are attempted even if one raises.  If any raise,
        the first exception is re-raised after all closures have been
        attempted.
        """
        errors: list[Exception] = []
        for spec in reversed(tuple(self._specs.values())):
            for resource in reversed(spec.resources):
                try:
                    await resource.close()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
        if errors:
            raise errors[0]
