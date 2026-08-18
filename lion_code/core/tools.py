"""Pi-compatible provider-neutral tool definitions and execution results."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, model_validator

from lion_code.core.cancellation import CancellationView
from lion_code.core.messages import ImageContent, TextContent, ToolCall, WireModel
from lion_code.core.types import JSONValue


class AgentToolResult(WireModel):
    """Final or partial result produced by a tool."""

    content: list[TextContent | ImageContent] = Field(default_factory=list)
    details: JSONValue = None
    added_tool_names: list[str] | None = None
    terminate: bool | None = None

    # Lion extension: preserve ToolRuntime's structured error state so that
    # permission denials, hook rejections, and freshness failures surfaced by
    # the host runtime are not reclassified as successful tool calls.
    is_error: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_text_content(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        content = data.get("content")
        if isinstance(content, str):
            data["content"] = [TextContent(text=content)] if content else []
        return data

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.content if isinstance(block, TextContent))


ToolUpdateCallback = Callable[[AgentToolResult], None]


class ToolExecutor(Protocol):
    def __call__(
        self,
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: CancellationView | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> Awaitable[AgentToolResult]:
        """Execute one validated tool call."""
        ...


ToolExecutionMode = Literal["sequential", "parallel"]


@dataclass(frozen=True, slots=True)
class AgentTool:
    """A tool exposed to the portable agent loop."""

    name: str
    description: str
    parameters: Mapping[str, JSONValue]
    execute_fn: ToolExecutor
    execution_mode: ToolExecutionMode = "parallel"

    @property
    def input_schema(self) -> Mapping[str, JSONValue]:
        """Alias used by provider payload builders."""
        return self.parameters

    async def execute(
        self,
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: CancellationView | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        """Execute a tool with Pi-compatible call-id and progress semantics."""
        return await self.execute_fn(tool_call_id, arguments, signal, on_update)


__all__ = [
    "AgentTool",
    "AgentToolResult",
    "ToolCall",
    "ToolExecutionMode",
    "ToolExecutor",
    "ToolUpdateCallback",
]
