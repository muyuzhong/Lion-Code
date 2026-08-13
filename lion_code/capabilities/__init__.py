"""Capability SPI: stable extension slots for Agent-level capabilities.

This package provides the foundational types and registry for declaring
capabilities that extend Agent behavior through narrow extension slots.

Design principles
-----------------
- Kernel and Capability are strictly separated.
- A Capability declares *what the Agent can do*, not *how the Agent runs*.
- ``CapabilitySpec`` is immutable; extension slots are narrow protocols.
- ``CapabilityRegistry`` organizes contributions-it is NOT a service locator.
- Capabilities must not depend on ``Agent`` or ``AgentHarness``.

Concrete capability implementations live in sub-modules:
- ``mcp``: MCP tool discovery and registration (TurnParticipant)
- ``skill``: Skill tool contribution (ToolSource)
- ``subagent``: Sub-agent tool contribution (ToolSource)
- ``plan``: Plan mode tool contribution (ToolSource)
"""

from __future__ import annotations

from .mcp import McpCapability
from .plan import create_plan_capability
from .registry import (
    CapabilityRegistry,
    CircularDependencyError,
    DuplicateCapabilityError,
    MissingDependencyError,
)
from .skill import create_skill_capability
from .subagent import create_subagent_capability
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
    "McpCapability",
    "MissingDependencyError",
    "PromptLayer",
    "SessionParticipant",
    "ToolSource",
    "TurnParticipant",
    "create_plan_capability",
    "create_skill_capability",
    "create_subagent_capability",
]
