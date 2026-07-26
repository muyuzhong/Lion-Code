"""前端渲染扩展点的类型别名(vendored 自 tau_coding/extensions/api.py 子集)。

Lion 暂无扩展运行时;保留这三个可选渲染器契约使 state/widgets 与上游
保持同构,前端可按需注入自定义渲染。返回 Rich markup(或普通)字符串,
返回 ``None`` 表示回退默认渲染。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from lion_code.core.tools import AgentToolResult
from lion_code.core.types import JSONValue

# 自定义消息渲染:(custom_type, text, details, expanded) -> markup | None
CustomMessageMarkup = Callable[
    [str, str, "Mapping[str, JSONValue] | None", bool], "str | None"
]

# 工具调用行渲染:(tool_name, arguments) -> markup | None
ToolCallMarkup = Callable[[str, "Mapping[str, JSONValue]"], "str | None"]

# 工具结果渲染:(tool_name, result, expanded) -> markup | None
ToolResultMarkup = Callable[[str, AgentToolResult, bool], "str | None"]

__all__ = ["CustomMessageMarkup", "ToolCallMarkup", "ToolResultMarkup"]
