"""agent 层共享的底层 JSON 类型别名。"""

from __future__ import annotations

# Pydantic 需要 PEP 695 命名递归别名，才能正确处理嵌套 JSON 值。
type JSONPrimitive = str | int | float | bool | None
type JSONValue = JSONPrimitive | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]
