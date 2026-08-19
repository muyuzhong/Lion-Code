"""SubAgent Capability：向 Registry 提供已绑定执行器的 ``agent`` 工具。"""

from __future__ import annotations

from .runtime import SubagentExecutor
from ...tooling.internal import create_agent_tool
from ...tooling.types import LionTool
from ..types import CapabilitySpec


class _SubagentToolSource:
    """Provides the ``agent`` (sub-agent) tool definition."""

    def __init__(self, executor: SubagentExecutor) -> None:
        self._tool: LionTool = create_agent_tool(executor)

    def tools(self) -> list[LionTool]:
        return [self._tool]


def create_subagent_capability(executor: SubagentExecutor) -> CapabilitySpec:
    """返回提供已绑定 ``agent`` 工具的 Capability。"""
    return CapabilitySpec(
        name="subagent",
        tool_sources=(_SubagentToolSource(executor),),
    )
