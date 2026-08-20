"""通过 ModelProvider 生成上下文摘要的供应商无关契约。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lion_code.core.messages import AgentMessage, UserMessage
from lion_code.core.provider import ModelProvider
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent

SUMMARY_SYSTEM_PROMPT = (
    "You summarize coding-agent conversations. Preserve only concrete facts needed "
    "to continue the current task and follow the requested output protocol."
)
OBJECTIVE_UNAVAILABLE_MARKER = "[objective unavailable; do not invent a goal]"
COMPACTION_PROMPT_TEMPLATE = """Summarize the old history for the next coding-agent turn.

Current objective:
{objective}

Recent context is background only. Do not compress it into the old-history summary, but use it
to understand the current state and continue the task:
<recent_context>
{recent_context}
</recent_context>

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


class CompactionPlanView(Protocol):
    """压缩目标读取所需的只读 Plan 投影。"""

    @property
    def is_active(self) -> bool: ...

    @property
    def file_path(self) -> Path | None: ...


@dataclass(frozen=True, slots=True)
class CompactionRequest:
    """一次压缩调用的旧历史、近期背景和目标快照。"""

    history: tuple[AgentMessage, ...]
    recent_context: tuple[AgentMessage, ...] = ()
    objective: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", tuple(self.history))
        object.__setattr__(self, "recent_context", tuple(self.recent_context))


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
        projected = [message.model_copy(deep=True) for message in request.history]
        projected.append(UserMessage(content=_render_compaction_prompt(request)))
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
        return summary


def resolve_compaction_objective(
    *,
    requested_objective: str | None,
    history: tuple[AgentMessage, ...],
    recent_context: tuple[AgentMessage, ...],
    plan_view: CompactionPlanView | None,
) -> str | None:
    """按当前指令、近期用户消息和活跃 Plan 解析本次压缩目标。"""

    objective = _clean_text(requested_objective)
    if objective is None:
        objective = _latest_user_message(recent_context)
    if objective is None:
        objective = _latest_user_message(history)

    plan = _read_active_plan(plan_view)
    parts: list[str] = []
    if objective is not None:
        parts.append(f"Current task:\n{objective}")
    if plan is not None:
        path, content = plan
        parts.append(f"Active plan ({path}):\n{content}")
    return "\n\n".join(parts) or None


def _render_compaction_prompt(request: CompactionRequest) -> str:
    objective = request.objective or OBJECTIVE_UNAVAILABLE_MARKER
    recent_context = _render_messages(request.recent_context) or "(none)"
    return COMPACTION_PROMPT_TEMPLATE.format(
        objective=objective,
        recent_context=recent_context,
    )


def _render_messages(messages: tuple[AgentMessage, ...]) -> str:
    rendered: list[str] = []
    for message in messages:
        text = message.text.strip()
        if not text:
            text = message.model_dump_json()
        rendered.append(f"[{message.role}]\n{text}")
    return "\n\n".join(rendered)


def _latest_user_message(messages: tuple[AgentMessage, ...]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, UserMessage):
            text = _clean_text(message.text)
            if text is not None and not text.startswith(
                "Previous conversation summary:"
            ):
                return text
    return None


def _read_active_plan(
    plan_view: CompactionPlanView | None,
) -> tuple[Path, str] | None:
    if plan_view is None or not plan_view.is_active:
        return None
    path = plan_view.file_path
    if path is None:
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if not content:
        return None
    return path, content


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
