"""内核终止契约：结构化运行结果与终止原因枚举（ADR-015）。

内核每次运行以一个 RunResult 收尾，让上层无需解析裸字符串即可区分
「正常未完成 / 预算耗尽 / Provider 失败 / 监督策略终止 / 意外异常」。
StopReason 继承 str，使 == 旧字符串仍成立，保护既有断言与 CLI 展示；
显式 __str__ 让 str()/format()/f-string 跨 3.10–3.13 都渲染为值而非成员名。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StopReason(str, Enum):
    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    MAX_TOKENS = "max_tokens"
    USER_ABORT = "user_abort"
    TOKEN_BUDGET = "token_budget"
    CONTEXT_OVERFLOW = "context_overflow"
    PROVIDER_ERROR = "provider_error"
    INCOMPLETE_STREAM = "incomplete_stream"
    SUPERVISOR_TERMINATE = "supervisor_terminate"
    FATAL = "fatal"

    def __str__(self) -> str:  # 让 str()/format()/f-string 渲染为值，CLI 展示不退化
        return self.value


@dataclass(frozen=True)
class RunResult:
    reason: StopReason
    final_message_id: Optional[str] = None
    error: Optional[str] = None    # 仅真正错误：provider_error / fatal / incomplete_stream / context_overflow
    detail: Optional[str] = None   # 非错误终止的具体说明：supervisor 的 constraint:max_tool_calls(52) 等
