"""Context projection contracts shared by Agent and benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lion_code.core.messages import AgentMessage


ContextActionType = Literal[
    "budget_tool_result",
    "snip_tool_result",
    "clear_tool_result",
    "request_compaction",
]


@dataclass(frozen=True, slots=True)
class ContextAction:
    """One observable rewrite made to the active model projection."""

    type: ContextActionType
    tool_call_id: str | None = None
    original_chars: int | None = None
    retained_chars: int | None = None


@dataclass(frozen=True, slots=True)
class ContextRuntimeState:
    """Runtime-only inputs used to select a projection policy."""

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
class PreparedContext:
    """Provider-bound projection plus the decisions that produced it."""

    messages: tuple[AgentMessage, ...]
    actions: tuple[ContextAction, ...] = ()
    estimated_tokens: int = 0
    compaction_required: bool = False
