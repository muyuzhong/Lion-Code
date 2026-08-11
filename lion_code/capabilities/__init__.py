"""Capability SPI: stable extension slots for Agent-level capabilities.

This package provides the foundational types and registry for declaring
capabilities that extend Agent behavior through narrow extension slots.

Design principles
-----------------
- Kernel and Capability are strictly separated.
- A Capability declares *what the Agent can do*, not *how the Agent runs*.
- ``CapabilitySpec`` is immutable; extension slots are narrow protocols.
- ``CapabilityRegistry`` organizes contributions—it is NOT a service locator.
- Capabilities must not depend on ``Agent`` or ``AgentHarness``.

Future capabilities (Browser, Sandbox, Checkpoint, Scheduler, ComputerUse)
will declare a ``CapabilitySpec`` and register it with the registry instead
of modifying the Agent主干.
"""

from __future__ import annotations

from .registry import (
    CapabilityRegistry,
    CircularDependencyError,
    DuplicateCapabilityError,
    MissingDependencyError,
)
from .types import (
    AsyncCloseable,
    CapabilitySpec,
    PromptLayer,
    SessionParticipant,
    ToolSource,
    TurnParticipant,
)

__all__ = [
    "AsyncCloseable",
    "CapabilityRegistry",
    "CapabilitySpec",
    "CircularDependencyError",
    "DuplicateCapabilityError",
    "MissingDependencyError",
    "PromptLayer",
    "SessionParticipant",
    "ToolSource",
    "TurnParticipant",
]
