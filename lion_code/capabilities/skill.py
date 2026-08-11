"""Skill Capability: contributes the ``skill`` tool to the registry.

The skill tool delegates to ``ToolContext.controller.run_skill_tool`` at
execution time.  The capability only provides the tool *definition*; the
business logic (inline / fork execution) remains in the Agent controller.
"""

from __future__ import annotations

from ..tooling.internal import create_skill_tool
from ..tooling.types import LionTool
from .types import CapabilitySpec


class _SkillToolSource:
    """Provides the ``skill`` tool definition."""

    def __init__(self) -> None:
        self._tool: LionTool = create_skill_tool()

    def tools(self) -> list[LionTool]:
        return [self._tool]


def create_skill_capability() -> CapabilitySpec:
    """Return a ``CapabilitySpec`` that contributes the ``skill`` tool."""
    return CapabilitySpec(
        name="skill",
        tool_sources=(_SkillToolSource(),),
    )
