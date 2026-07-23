"""统一工具执行入口。"""

from __future__ import annotations

from collections.abc import Mapping

from .context import ToolContext
from .registry import ToolRegistry
from .types import JSONValue, ToolResult, ToolUpdateCallback


class ToolRuntime:
    """解析并执行注册工具，把异常转换为结构化错误结果。"""

    def __init__(self, registry: ToolRegistry, context: ToolContext) -> None:
        self.registry = registry
        self.context = context

    async def execute(
        self,
        *,
        tool_call_id: str,
        name: str,
        arguments: Mapping[str, JSONValue],
        on_update: ToolUpdateCallback | None = None,
    ) -> ToolResult:
        try:
            tool = self.registry.resolve(name)
        except LookupError as exc:
            return ToolResult(content=str(exc), is_error=True)

        try:
            return await tool.execute(
                self.context,
                tool_call_id,
                arguments,
                on_update,
            )
        except Exception as exc:
            return ToolResult(
                content=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )
