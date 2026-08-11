"""SubAgent Capability: contributes the ``agent`` tool to the registry.

The agent tool delegates to ``ToolContext.controller.run_subagent_tool`` at
execution time.  The capability only provides the tool *definition*;
``SubagentFactory`` remains the independent domain service for child
construction.
"""

from __future__ import annotations

from ..tooling.internal import create_agent_tool
from ..tooling.types import LionTool
from .types import CapabilitySpec


class _SubagentToolSource:
    """Provides the ``agent`` (sub-agent) tool definition."""

    def __init__(self) -> None:
        self._tool: LionTool = create_agent_tool()

    def tools(self) -> list[LionTool]:
        return [self._tool]


def create_subagent_capability() -> CapabilitySpec:
    """Return a ``CapabilitySpec`` that contributes the ``agent`` tool."""
    return CapabilitySpec(
        name="subagent",
        tool_sources=(_SubagentToolSource(),),
    )
