"""通过 ModelProvider 生成上下文摘要的供应商无关契约。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from lion_code.context.estimator import (
    APPROXIMATE_CHARS_PER_TOKEN,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from lion_code.context.projector import budget_text
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider import ModelProvider
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent

SUMMARY_SYSTEM_PROMPT = (
    "You summarize coding-agent conversations. Preserve only concrete facts needed "
    "to continue the current task and follow the requested output protocol."
)
OBJECTIVE_UNAVAILABLE_MARKER = "[objective unavailable; do not invent a goal]"
HISTORY_OMITTED_MARKER = "[old history omitted by compaction input budget]"
_DYNAMIC_FIELD_BUDGET_RATIO = 0.05
_HINT_ITEM_LIMIT = 3
SUMMARY_HEADINGS = (
    "# Objective",
    "# Constraints",
    "# Decisions",
    "# Repository State",
    "# Findings",
    "# Failed Attempts",
    "# Completed Work",
    "# Remaining Work",
    "# Verification",
)
COMPACTION_PROMPT_TEMPLATE = """Summarize the old history for the next coding-agent turn.

Old history projection:
<history>
{history_projection}
</history>

Current objective:
{objective}

Recent context hint is bounded background only. Use it to understand the current state:
<recent_context_hint>
{recent_context_hint}
</recent_context_hint>

Return the summary using exactly these sections, in exactly this order:

# Objective
What problem is currently being solved.

# Constraints
Explicit user requirements, architecture boundaries, and forbidden changes.

# Decisions
Confirmed design decisions and the reasons for them.

# Repository State
Current branch, modified files, and important code locations.

# Findings
Confirmed facts and important source relationships.
Every Findings item MUST include a Coding Evidence line, such as
`file path::symbol`, a quoted source location, or another concrete code reference.
Evidence: <concrete source evidence>

# Failed Attempts
What was tried, why it failed, and what must not be repeated.

# Completed Work
Work already completed.

# Remaining Work
The next concrete steps required to finish the objective.

# Verification
Tests and checks already run, with their outcomes and current failures.
Every Verification item MUST include a Coding Evidence line, such as a test command and
result, commit hash, or one-line error summary.
Evidence: <command/result, commit hash, or one-line error summary>

Do not invent objectives, repository state, findings, or verification results. Use the explicit
objective-unavailable marker when the objective is unknown.
"""


class InvalidCompactionSummary(RuntimeError):
    """模型摘要不满足固定章节契约。"""


@dataclass(frozen=True, slots=True)
class CompactionRequest:
    """一次压缩调用的有界 Provider 输入快照。"""

    history_projection: str
    objective: str | None
    recent_context_hint: str
    input_budget_tokens: int

    def __post_init__(self) -> None:
        if self.input_budget_tokens <= 0:
            raise ValueError("input_budget_tokens must be positive")


class ContextCompactor(Protocol):
    """把一段 canonical 历史压缩为可继续工作的文本摘要。"""

    async def summarize(self, request: CompactionRequest) -> str: ...


class ProviderContextCompactor:
    """仅通过 ModelProvider 事件流生成摘要，不调用任何供应商 SDK。"""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        get_model: Callable[[], str],
        system_prompt: str = SUMMARY_SYSTEM_PROMPT,
    ) -> None:
        self._provider = provider
        self._get_model = get_model
        self._system_prompt = system_prompt

    async def summarize(self, request: CompactionRequest) -> str:
        bounded_request = _fit_history_to_budget(request, self._system_prompt)
        projected = [UserMessage(content=_render_compaction_prompt(bounded_request))]
        if (
            estimate_compaction_input_tokens(
                bounded_request,
                system_prompt=self._system_prompt,
            )
            > bounded_request.input_budget_tokens
        ):
            raise RuntimeError("Context compaction input exceeds its budget")
        summary: str | None = None
        async for event in self._provider.stream_response(
            model=self._get_model(),
            system=self._system_prompt,
            messages=projected,
            tools=[],
            signal=None,
        ):
            if isinstance(event, AssistantDoneEvent):
                summary = event.message.text.strip()
            elif isinstance(event, AssistantErrorEvent):
                detail = event.error.error_message or event.error.text or event.reason
                raise RuntimeError(f"Context compaction failed: {detail}")

        if not summary:
            raise RuntimeError("Context compaction produced no summary")
        _validate_summary(summary)
        return summary


def build_compaction_request(
    *,
    history: tuple[AgentMessage, ...],
    recent_context: tuple[AgentMessage, ...],
    requested_objective: str | None,
    effective_window_tokens: int,
    input_ratio: float,
) -> CompactionRequest:
    """从 canonical messages 派生满足总输入预算的只读压缩快照。"""

    if effective_window_tokens <= 0:
        raise ValueError("effective_window_tokens must be positive")
    if not 0 < input_ratio <= 1:
        raise ValueError("input_ratio must be between 0 and 1")

    input_budget_tokens = max(1, int(effective_window_tokens * input_ratio))
    dynamic_budget_chars = (
        int(input_budget_tokens * _DYNAMIC_FIELD_BUDGET_RATIO)
        * APPROXIMATE_CHARS_PER_TOKEN
    )
    objective = resolve_compaction_objective(
        requested_objective=requested_objective,
        history=history,
        recent_context=recent_context,
    )
    bounded_objective = (
        budget_text(objective, dynamic_budget_chars) if objective is not None else None
    )
    hint = budget_text(
        _render_recent_context_hint(recent_context),
        dynamic_budget_chars,
    )
    request = CompactionRequest(
        history_projection=_render_messages(history),
        objective=bounded_objective or None,
        recent_context_hint=hint,
        input_budget_tokens=input_budget_tokens,
    )
    return _fit_history_to_budget(request, SUMMARY_SYSTEM_PROMPT)


def resolve_compaction_objective(
    *,
    requested_objective: str | None,
    history: tuple[AgentMessage, ...],
    recent_context: tuple[AgentMessage, ...],
) -> str | None:
    """按当前指令、近期用户消息和旧历史解析本次压缩目标。"""

    objective = _clean_text(requested_objective)
    if objective is None:
        objective = _latest_user_message(recent_context)
    if objective is None:
        objective = _latest_user_message(history)
    return f"Current task:\n{objective}" if objective is not None else None


def _render_compaction_prompt(request: CompactionRequest) -> str:
    objective = request.objective or OBJECTIVE_UNAVAILABLE_MARKER
    return COMPACTION_PROMPT_TEMPLATE.format(
        history_projection=request.history_projection or "(none)",
        objective=objective,
        recent_context_hint=request.recent_context_hint or "(none)",
    )


def _render_messages(messages: tuple[AgentMessage, ...]) -> str:
    rendered: list[str] = []
    for message in messages:
        text = message.text.strip()
        if not text:
            text = message.model_dump_json()
        rendered.append(f"[{message.role}]\n{text}")
    return "\n\n".join(rendered)


def _render_recent_context_hint(messages: tuple[AgentMessage, ...]) -> str:
    conclusion: str | None = None
    failed_tools: list[str] = []
    paths: list[str] = []

    for message in reversed(messages):
        if isinstance(message, ToolResultMessage) and message.is_error:
            if (
                message.tool_name not in failed_tools
                and len(failed_tools) < _HINT_ITEM_LIMIT
            ):
                failed_tools.append(message.tool_name)
        if not isinstance(message, AssistantMessage):
            continue
        if conclusion is None:
            conclusion = _clean_text(message.text)
        for call in reversed(message.tool_calls):
            raw_path = call.arguments.get("file_path") or call.arguments.get("path")
            if (
                isinstance(raw_path, str)
                and raw_path
                and raw_path not in paths
                and len(paths) < _HINT_ITEM_LIMIT
            ):
                paths.append(raw_path)

    sections: list[str] = []
    if conclusion is not None:
        sections.append(f"Last assistant conclusion:\n{conclusion}")
    if failed_tools:
        sections.append(
            "Recent failed tools:\n" + "\n".join(f"- {name}" for name in failed_tools)
        )
    if paths:
        sections.append(
            "Recent file paths:\n" + "\n".join(f"- {path}" for path in paths)
        )
    return "\n\n".join(sections)


def estimate_compaction_input_tokens(
    request: CompactionRequest,
    *,
    system_prompt: str = SUMMARY_SYSTEM_PROMPT,
) -> int:
    """估算一次 compactor Provider 调用的完整输入 token。"""

    messages = (UserMessage(content=_render_compaction_prompt(request)),)
    return estimate_text_tokens(system_prompt) + estimate_messages_tokens(messages)


def _fit_history_to_budget(
    request: CompactionRequest,
    system_prompt: str,
) -> CompactionRequest:
    if estimate_compaction_input_tokens(request, system_prompt=system_prompt) <= (
        request.input_budget_tokens
    ):
        return request

    without_history = replace(request, history_projection="")
    fixed_only = replace(without_history, objective=None, recent_context_hint="")
    if estimate_compaction_input_tokens(fixed_only, system_prompt=system_prompt) > (
        request.input_budget_tokens
    ):
        raise RuntimeError("Fixed context compaction prompt exceeds its input budget")
    if estimate_compaction_input_tokens(
        without_history, system_prompt=system_prompt
    ) > (request.input_budget_tokens):
        raise RuntimeError(
            "Context compaction objective and hint exceed the input budget"
        )

    source = request.history_projection
    best = without_history
    omitted = replace(without_history, history_projection=HISTORY_OMITTED_MARKER)
    if estimate_compaction_input_tokens(omitted, system_prompt=system_prompt) <= (
        request.input_budget_tokens
    ):
        best = omitted

    low = 1
    high = len(source)
    while low <= high:
        budget = (low + high) // 2
        candidate = replace(
            request,
            history_projection=budget_text(source, budget),
        )
        if estimate_compaction_input_tokens(candidate, system_prompt=system_prompt) <= (
            request.input_budget_tokens
        ):
            best = candidate
            low = budget + 1
        else:
            high = budget - 1
    return best


def _validate_summary(summary: str) -> None:
    lines = [line.strip() for line in summary.splitlines()]
    positions: list[int] = []
    for heading in SUMMARY_HEADINGS:
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise InvalidCompactionSummary(
                f"Compaction summary must contain {heading!r} exactly once"
            )
        positions.append(matches[0])
    if positions != sorted(positions):
        raise InvalidCompactionSummary(
            "Compaction summary sections are not in the required order"
        )


def _latest_user_message(messages: tuple[AgentMessage, ...]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, UserMessage):
            text = _clean_text(message.text)
            if text is not None and not text.startswith(
                "Previous conversation summary:"
            ):
                return text
    return None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
