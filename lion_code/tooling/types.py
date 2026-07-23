"""统一工具对象使用的基础类型。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from .context import ToolContext


JSONValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)


@dataclass(frozen=True, slots=True)
class ToolCapabilities:
    """描述运行时可据此调度工具的稳定能力。"""

    read_only: bool = False
    mutates_workspace: bool = False
    executes_process: bool = False
    external_side_effect: bool = False
    concurrency_safe: bool = False
    allowed_in_plan: bool = False
    requires_read_before_write: bool = False
    tracks_read_freshness: bool = False
    requires_confirmation: bool = False
    deferred: bool = False
    result_policy: Literal["normal", "snippable", "persist_large"] = "normal"


@dataclass(slots=True)
class ToolResult:
    """工具执行的结构化结果。"""

    content: str
    is_error: bool = False
    details: dict[str, JSONValue] = field(default_factory=dict)
    activated_tools: list[str] = field(default_factory=list)
    terminate: bool = False


ToolUpdateCallback: TypeAlias = Callable[
    [ToolResult],
    Awaitable[None] | None,
]

ToolExecutor = Callable[
    [
        "ToolContext",
        str,
        Mapping[str, JSONValue],
        ToolUpdateCallback | None,
    ],
    Awaitable[ToolResult],
]


@dataclass(frozen=True, slots=True)
class LionTool:
    """把模型 Schema、执行函数和运行能力绑定为一个不可变工具。"""

    name: str
    label: str
    description: str
    parameters: Mapping[str, JSONValue]
    execute_fn: ToolExecutor
    capabilities: ToolCapabilities = ToolCapabilities()
    prompt_snippet: str | None = None
    prompt_guidelines: tuple[str, ...] = ()
    execution_mode: Literal["sequential", "parallel"] = "sequential"

    async def execute(
        self,
        context: "ToolContext",
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        on_update: ToolUpdateCallback | None = None,
    ) -> ToolResult:
        """按统一签名执行工具。"""
        return await self.execute_fn(context, tool_call_id, arguments, on_update)

    def to_anthropic_schema(self) -> dict:
        """返回 Anthropic 工具 Schema。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.parameters),
        }

    def to_openai_schema(self) -> dict:
        """返回 OpenAI function 工具 Schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }
