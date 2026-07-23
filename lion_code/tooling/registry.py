"""Agent 实例本地的工具注册中心。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

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

    def unregister(self, name: str) -> None:
        """移除工具定义及其激活状态。"""
        self._tools.pop(name, None)
        self._active.discard(name)

    def is_active(self, name: str) -> bool:
        """返回工具是否已注册且处于激活状态。"""
        return name in self._tools and name in self._active

    def all_tools(self) -> list[LionTool]:
        """按注册顺序返回全部定义，包括尚未激活的延迟工具。"""
        return list(self._tools.values())

    def filtered(
        self,
        predicate: Callable[[LionTool], bool],
    ) -> "ToolRegistry":
        """创建共享不可变工具对象、但拥有独立激活状态的受限视图。"""
        child = ToolRegistry()
        for tool in self._tools.values():
            if predicate(tool):
                child.register(tool, activate=self.is_active(tool.name))
        return child

    def deferred_tool_names(self) -> list[str]:
        """返回当前尚未激活的延迟工具名称。"""
        return [
            tool.name
            for tool in self._tools.values()
            if tool.capabilities.deferred and tool.name not in self._active
        ]

    def search(self, query: str) -> list[LionTool]:
        """按名称和描述进行不区分大小写的子串搜索。"""
        needle = query.casefold()
        return [
            tool
            for tool in self._tools.values()
            if needle in tool.name.casefold()
            or needle in tool.description.casefold()
        ]

    @contextmanager
    def temporary_tool(self, tool: LionTool) -> Iterator[LionTool]:
        """在上下文内临时注册并激活工具，退出时精确恢复原状态。"""
        previous = self._tools.get(tool.name)
        previous_active = tool.name in self._active
        self.register(tool, replace=True, activate=True)
        try:
            yield tool
        finally:
            if previous is None:
                self.unregister(tool.name)
            else:
                self.register(
                    previous,
                    replace=True,
                    activate=previous_active,
                )
