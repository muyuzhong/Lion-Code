"""Plan Capability：把 PlanRuntime 命令绑定为两个 ToolSource 工具。"""

from __future__ import annotations

from collections.abc import Mapping

from ..plan_runtime import PlanRuntime, PlanToolOutcome, PlanView
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


class PlanPromptLayer:
    """把实时 Plan View 投影为当前 system prompt 片段。"""

    layer_id = "plan"

    def __init__(self, view: PlanView) -> None:
        self._view = view

    def render(self) -> str:
        if not self._view.is_active:
            return ""
        return f"""# Plan Mode Active

Plan mode is active. You MUST NOT make any edits (except the plan file below), run non-readonly tools, or make any changes to the system.

## Plan File: {self._view.file_path}
Write your plan incrementally to this file using write_file or edit_file. This is the ONLY file you are allowed to edit.

## Workflow
1. **Explore**: Read code to understand the task. Use read_file, list_files, grep_search.
2. **Design**: Design your implementation approach. Use the agent tool with type="plan" if the task is complex.
3. **Write Plan**: Write a structured plan to the plan file including:
   - **Context**: Why this change is needed
   - **Steps**: Implementation steps with critical file paths
   - **Verification**: How to test the changes
4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

IMPORTANT: When your plan is complete, you MUST call exit_plan_mode. Do NOT ask the user to approve — exit_plan_mode handles that."""


class PlanSessionParticipant:
    """把会话迁移适配到 Plan runtime Owner。"""

    def __init__(self, runtime: PlanRuntime) -> None:
        self._runtime = runtime

    async def on_new_session(self) -> None:
        self._runtime.reset_for_new_session()

    async def on_restore_session(self) -> None:
        self._runtime.reset_after_restore()


def create_plan_capability(runtime: PlanRuntime) -> CapabilitySpec:
    """返回唯一 Plan Capability 及其窄投影贡献。"""

    return CapabilitySpec(
        name="plan",
        tool_sources=(_PlanToolSource(runtime),),
        prompt_layers=(PlanPromptLayer(runtime),),
        session_participants=(PlanSessionParticipant(runtime),),
    )


def _tool_result(outcome: PlanToolOutcome) -> ToolResult:
    return ToolResult(content=outcome.content, terminate=outcome.terminate)
