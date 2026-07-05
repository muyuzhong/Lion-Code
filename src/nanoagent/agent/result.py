from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StopReason(str, Enum):
    """run 级终止原因，描述整个 agent loop 为什么停止。

    与 nanoagent.ai.StopReason 区分开；后者只描述单条模型消息的 wire 层停止原因。
    """

    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    ABORTED = "aborted"
    ERROR = "error"


@dataclass
class RunResult:
    """一次 agent run 的最终结果摘要。"""

    reason: StopReason
    final_message_id: str | None = None
    error: str | None = None
    detail: dict | None = None

    @property
    def succeeded(self) -> bool:
        return self.reason is StopReason.COMPLETED
