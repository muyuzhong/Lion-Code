"""Skill Capability：向 Registry 提供已绑定运行时的 ``skill`` 工具。"""

from __future__ import annotations

from ...tooling.internal import create_skill_tool
from ...tooling.types import LionTool
from ..types import CapabilitySpec
from .runtime import SkillRuntime


class _SkillToolSource:
    """Provides the ``skill`` tool definition."""

    def __init__(self, runtime: SkillRuntime) -> None:
        self._tool: LionTool = create_skill_tool(runtime)

    def tools(self) -> list[LionTool]:
        return [self._tool]


def create_skill_capability(runtime: SkillRuntime) -> CapabilitySpec:
    """返回提供已绑定 ``skill`` 工具的 Capability。"""
    return CapabilitySpec(
        name="skill",
        tool_sources=(_SkillToolSource(runtime),),
    )
