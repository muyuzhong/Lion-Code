"""Plan Capability：把 PlanRuntime 命令绑定为两个 ToolSource 工具。"""

from __future__ import annotations

from collections.abc import Mapping

from ..plan_runtime import PlanRuntime, PlanToolOutcome
from ..tooling.internal import (
    create_enter_plan_tool,
    create_exit_plan_tool,
)
from ..tooling.types import JSONValue, LionTool, ToolResult
from .types import CapabilitySpec


class _PlanToolSource:
    """提供直接绑定同一个 ``PlanRuntime`` 的 enter/exit 工具。"""

    def __init__(self, runtime: PlanRuntime) -> None:
        async def enter(arguments: Mapping[str, JSONValue]) -> ToolResult:
            del arguments
            return _tool_result(runtime.enter())

        async def exit_(arguments: Mapping[str, JSONValue]) -> ToolResult:
            del arguments
            return _tool_result(await runtime.exit())

        self._tools: tuple[LionTool, ...] = (
            create_enter_plan_tool(enter),
            create_exit_plan_tool(exit_),
        )

    def tools(self) -> tuple[LionTool, ...]:
        return self._tools


def create_plan_capability(runtime: PlanRuntime) -> CapabilitySpec:
    """返回只贡献 Plan 工具、且不持有额外状态的 Capability。"""

    return CapabilitySpec(
        name="plan",
        tool_sources=(_PlanToolSource(runtime),),
    )


def _tool_result(outcome: PlanToolOutcome) -> ToolResult:
    return ToolResult(content=outcome.content, terminate=outcome.terminate)
