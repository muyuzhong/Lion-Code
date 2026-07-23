"""根据能力和名称为子 Agent 构造工具注册表视图。"""

from __future__ import annotations

from dataclasses import dataclass

from .registry import ToolRegistry
from .types import LionTool


@dataclass(frozen=True, slots=True)
class ToolSelectionPolicy:
    """声明子运行时可以继承的工具范围。"""

    allowed_names: frozenset[str] | None = None
    require_read_only: bool = False
    exclude_names: frozenset[str] = frozenset()


def select_tools(
    parent: ToolRegistry,
    policy: ToolSelectionPolicy,
) -> ToolRegistry:
    """按策略选择父注册表工具，并隔离子注册表的激活状态。"""

    def allowed(tool: LionTool) -> bool:
        if tool.name in policy.exclude_names:
            return False
        if (
            policy.allowed_names is not None
            and tool.name not in policy.allowed_names
        ):
            return False
        if policy.require_read_only and not tool.capabilities.read_only:
            return False
        return True

    return parent.filtered(allowed)
