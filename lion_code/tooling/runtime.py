"""统一工具执行入口。"""

from __future__ import annotations

from collections.abc import Mapping

from .registry import ToolRegistry
from .types import JSONValue, ToolResult


class ToolRuntime:
    """解析并执行注册工具，把异常转换为结构化错误结果。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        *,
        tool_call_id: str,
        name: str,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        try:
            tool = self.registry.resolve(name)
        except LookupError as exc:
            return ToolResult(content=str(exc), is_error=True)

        try:
            return await tool.execute(tool_call_id, arguments)
        except Exception as exc:
            return ToolResult(
                content=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )
