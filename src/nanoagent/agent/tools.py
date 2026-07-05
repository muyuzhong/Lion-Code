"""与 provider 无关的工具定义、工具调用和执行结果。"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from nanoagent.agent.types import JSONValue


class ToolCancellationToken(Protocol):
    """工具执行时可接收的最小取消信号接口。"""

    def is_cancelled(self) -> bool:
        """返回当前工具执行是否应该停止。"""
        ...


class ToolExecutor(Protocol):
    """实际执行工具的异步可调用对象。"""

    def __call__(
        self,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
    ) -> Awaitable[AgentToolResult]:
        """使用 JSON-like 参数执行工具，并可接收取消信号。"""
        ...


class ToolCall(BaseModel):
    """发出的工具执行请求。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, JSONValue] = Field(default_factory=dict)


class AgentToolResult(BaseModel):
    """工具执行后返回的结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    ok: bool
    content: str
    data: dict[str, JSONValue] | None = None
    details: dict[str, JSONValue] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AgentTool:
    """可暴露给 agent loop 的工具声明和执行入口。"""

    name: str
    description: str
    input_schema: Mapping[str, JSONValue]
    executor: ToolExecutor
    prompt_snippet: str | None = None
    prompt_guidelines: tuple[str, ...] = ()

    async def execute(
        self,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
    ) -> AgentToolResult:
        """用 provider 无关的 JSON-like 参数执行工具。"""
        return await self.executor(arguments, signal=signal)
