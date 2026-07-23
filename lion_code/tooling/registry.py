"""Agent 实例本地的工具注册中心。"""

from __future__ import annotations

from .types import LionTool


class ToolRegistry:
    """注册工具并维护当前 Agent 独立的激活状态。"""

    def __init__(self) -> None:
        self._tools: dict[str, LionTool] = {}
        self._active: set[str] = set()

    def register(
        self,
        tool: LionTool,
        *,
        replace: bool = False,
        activate: bool | None = None,
    ) -> None:
        """注册工具；默认只激活非延迟工具。"""
        if tool.name in self._tools and not replace:
            raise ValueError(f"Duplicate tool: {tool.name}")

        self._tools[tool.name] = tool
        enabled = not tool.capabilities.deferred if activate is None else activate
        if enabled:
            self._active.add(tool.name)
        else:
            self._active.discard(tool.name)

    def resolve(self, name: str) -> LionTool:
        """解析已注册工具，未知名称使用稳定的 LookupError 契约。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise LookupError(f"Unknown tool: {name}") from exc

    def active_tools(self) -> list[LionTool]:
        """按注册顺序返回当前激活工具。"""
        return [
            tool
            for name, tool in self._tools.items()
            if name in self._active
        ]

    def activate(self, name: str) -> LionTool:
        """激活已注册工具并返回工具对象。"""
        tool = self.resolve(name)
        self._active.add(name)
        return tool

    def deactivate(self, name: str) -> None:
        """停用工具但保留注册定义。"""
        self._active.discard(name)
