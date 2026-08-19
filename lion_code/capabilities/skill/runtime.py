"""Skill 查找与 inline/fork 执行策略。"""

from __future__ import annotations

from collections.abc import Mapping

from . import discovery
from ..subagent.runtime import SubagentExecutor
from ...tooling.types import JSONValue, ToolResult


class SkillRuntime:
    """拥有 Skill 查找、参数解析和 fork 委托的运行时边界。"""

    def __init__(self, executor: SubagentExecutor) -> None:
        self._executor = executor

    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        """执行一次 Skill 工具调用并返回结构化结果。"""

        skill_name = _string_argument(arguments, "skill_name", "")
        args = _string_argument(arguments, "args", "")
        result = discovery.execute_skill(skill_name, args)
        if not result:
            return ToolResult(content=f"Unknown skill: {skill_name}")

        prompt = str(result["prompt"])
        if result["context"] == "fork":
            return await self._executor.execute_skill_fork(
                skill_name=skill_name,
                prompt=prompt,
                allowed_tools=result.get("allowed_tools"),
                args=args,
            )

        return ToolResult(
            content=f'[Skill "{skill_name}" activated]\n\n{prompt}',
        )


def _string_argument(
    arguments: Mapping[str, JSONValue],
    name: str,
    default: str,
) -> str:
    value = arguments.get(name, default)
    return value if isinstance(value, str) else str(value)
