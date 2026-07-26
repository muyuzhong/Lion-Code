"""Agent 与基准共用的 Context 投影契约。"""

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
class PreparedContext:
    """发往 Provider 的投影及其派生决策。"""

    messages: tuple[AgentMessage, ...]
    actions: tuple[ContextAction, ...] = ()
    estimated_tokens: int = 0
    compaction_required: bool = False
