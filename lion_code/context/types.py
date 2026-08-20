"""Agent 与基准共用的 Context 投影契约。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    ToolResultMessage,
)

ContextActionType = Literal[
    "budget_tool_result",
    "snip_tool_result",
    "clear_tool_result",
    "request_compaction",
]

CompactionStatus = Literal["not required", "required"]

MAX_TOOL_ARGUMENT_SUMMARY_CHARS = 240
MAX_FAILURE_SUMMARY_CHARS = 240
_TOOL_ACTIVITY_LIMIT = 3


@dataclass(frozen=True, slots=True)
class ContextAction:
    """活跃模型投影中的一次可观测改写。"""

    type: ContextActionType
    tool_call_id: str | None = None
    original_chars: int | None = None
    retained_chars: int | None = None


@dataclass(frozen=True, slots=True)
class ContextRuntimeState:
    """选择投影策略所需、但不进入持久历史的运行态输入。"""

    effective_window_tokens: int
    last_prompt_tokens: int
    last_model_call_at: float | None = None
    now: float | None = None

    @property
    def utilization(self) -> float:
        if self.effective_window_tokens <= 0:
            return 0.0
        return self.last_prompt_tokens / self.effective_window_tokens


@dataclass(frozen=True, slots=True)
class ContextUtilization:
    """单次请求的只读 token 用量与 compaction 投影。"""

    used_tokens: int
    limit_tokens: int
    percentage: float
    compaction: CompactionStatus = "not required"

    @property
    def compaction_required(self) -> bool:
        """返回供决策调用方使用的布尔形式。"""
        return self.compaction == "required"


@dataclass(frozen=True, slots=True)
class ToolTrace:
    """不可变的工具调用名称、参数投影与聚合次数。"""

    tool_name: str
    argument_summary: str
    count: int = 1

    @property
    def name(self) -> str:
        """返回与 canonical ``ToolCall.name`` 对应的名称。"""
        return self.tool_name

    @property
    def arguments(self) -> str:
        """返回摘要，不暴露原始可变参数映射。"""
        return self.argument_summary

    @property
    def summary(self) -> str:
        """返回适合状态栏展示和重复聚合的单条调用摘要。"""
        if not self.argument_summary:
            return f"{self.tool_name}()"
        return f"{self.tool_name}({self.argument_summary})"


@dataclass(frozen=True, slots=True)
class ContextView:
    """提供给 ``ContextLayer`` 的不可变单次请求状态视图。

    视图只保留从源消息派生的字符串、数字和 tuple；不保存消息、参数
    映射、traceback 或其他可变 Runtime Owner。
    """

    current_time: str
    context_utilization: ContextUtilization
    tool_totals: tuple[ToolTrace, ...] = ()
    recent_tool_calls: tuple[ToolTrace, ...] = ()
    repeated_tool_calls: tuple[ToolTrace, ...] = ()
    other_tool_calls: int = 0
    recent_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_totals", tuple(self.tool_totals))
        object.__setattr__(self, "recent_tool_calls", tuple(self.recent_tool_calls))
        object.__setattr__(
            self,
            "repeated_tool_calls",
            tuple(self.repeated_tool_calls),
        )
        object.__setattr__(self, "recent_failures", tuple(self.recent_failures))

    @classmethod
    def from_messages(
        cls,
        messages: Iterable[AgentMessage],
        state: ContextRuntimeState | None = None,
        *,
        current_time: str | None = None,
        used_tokens: int | None = None,
        limit_tokens: int | None = None,
        compaction: CompactionStatus | None = None,
        compaction_required: bool | None = None,
    ) -> ContextView:
        """从消息和标量 Runtime 值构造视图。

        ``messages`` 只消费一次，并且只保留不可变标量投影；``state`` 是
        ContextManager 的便捷输入，显式 token 值优先于其中的同名字段。
        """

        message_list = tuple(messages)
        if state is not None:
            used = state.last_prompt_tokens if used_tokens is None else used_tokens
            limit = (
                state.effective_window_tokens if limit_tokens is None else limit_tokens
            )
            if current_time is None:
                current_time = _format_current_time(state.now)
        else:
            used = 0 if used_tokens is None else used_tokens
            limit = 0 if limit_tokens is None else limit_tokens
        if current_time is None:
            current_time = _format_current_time(None)

        if compaction_required is not None:
            compaction_status: CompactionStatus = (
                "required" if compaction_required else "not required"
            )
        else:
            compaction_status = compaction or "not required"

        tool_totals: dict[str, int] = {}
        trace_totals: dict[str, tuple[ToolTrace, int]] = {}
        recent_traces: list[ToolTrace] = []
        for message in message_list:
            if not isinstance(message, AssistantMessage):
                continue
            for call in message.tool_calls:
                trace = ToolTrace(
                    tool_name=call.name,
                    argument_summary=_summarize_arguments(call.arguments),
                )
                tool_totals[call.name] = tool_totals.get(call.name, 0) + 1
                previous = trace_totals.get(trace.summary)
                trace_totals[trace.summary] = (
                    trace,
                    1 if previous is None else previous[1] + 1,
                )
                recent_traces.append(trace)
                if len(recent_traces) > _TOOL_ACTIVITY_LIMIT:
                    del recent_traces[0]

        ranked_tools = sorted(tool_totals.items(), key=lambda item: -item[1])
        bounded_tool_totals = tuple(
            ToolTrace(tool_name=name, argument_summary="", count=count)
            for name, count in ranked_tools[:_TOOL_ACTIVITY_LIMIT]
        )
        repeated_traces = tuple(
            ToolTrace(
                tool_name=trace.tool_name,
                argument_summary=trace.argument_summary,
                count=count,
            )
            for trace, count in sorted(
                trace_totals.values(),
                key=lambda item: -item[1],
            )
            if count > 1
        )[:_TOOL_ACTIVITY_LIMIT]
        failures = tuple(
            _summarize_failure(message)
            for message in message_list
            if isinstance(message, ToolResultMessage) and message.is_error
        )[-3:]
        return cls(
            current_time=current_time,
            context_utilization=_context_utilization(
                used,
                limit,
                compaction_status,
            ),
            tool_totals=bounded_tool_totals,
            recent_tool_calls=tuple(recent_traces),
            repeated_tool_calls=repeated_traces,
            other_tool_calls=sum(
                count for _name, count in ranked_tools[_TOOL_ACTIVITY_LIMIT:]
            ),
            recent_failures=failures,
        )


@dataclass(frozen=True, slots=True)
class PreparedContext:
    """发往 Provider 的投影及其派生决策。"""

    messages: tuple[AgentMessage, ...]
    actions: tuple[ContextAction, ...] = ()
    estimated_tokens: int = 0
    compaction_required: bool = False


def _context_utilization(
    used_tokens: int,
    limit_tokens: int,
    compaction: CompactionStatus,
) -> ContextUtilization:
    percentage = 0.0 if limit_tokens <= 0 else (used_tokens / limit_tokens) * 100
    return ContextUtilization(
        used_tokens=used_tokens,
        limit_tokens=limit_tokens,
        percentage=percentage,
        compaction=compaction,
    )


def _summarize_arguments(arguments: Mapping[str, object]) -> str:
    """以确定性 key=value 形式生成有限长度的参数摘要。"""
    parts: list[str] = []
    for key in sorted(arguments):
        display_key = "path" if key == "file_path" else key
        parts.append(f"{display_key}={_summarize_value(arguments[key])}")
    return _bounded_text(", ".join(parts), MAX_TOOL_ARGUMENT_SUMMARY_CHARS)


def _summarize_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _summarize_failure(message: ToolResultMessage) -> str:
    """只保留一行失败摘要，不把 traceback 带入状态栏。"""
    parts = [part.strip() for part in message.text.splitlines() if part.strip()]
    line = next(
        (
            part
            for part in parts
            if not part.startswith("Traceback (most recent call last):")
            and not part.startswith('File "')
        ),
        "error details unavailable",
    )
    details = message.details
    exit_code: object | None = None
    if isinstance(details, Mapping):
        exit_code = details.get("exit_code", details.get("exitCode"))
    if isinstance(exit_code, (int, str)) and not isinstance(exit_code, bool):
        line = f"{line}, exit={exit_code}"
    return _bounded_text(f"{message.tool_name}: {line}", MAX_FAILURE_SUMMARY_CHARS)


def _bounded_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "..."
    head = max(0, (limit - len(marker)) // 2)
    tail = max(0, limit - len(marker) - head)
    return text[:head] + marker + text[-tail:]


def _format_current_time(timestamp: float | None) -> str:
    value = (
        datetime.now(UTC)
        if timestamp is None
        else datetime.fromtimestamp(
            timestamp,
            tz=UTC,
        )
    )
    return value.isoformat(timespec="seconds")
