"""Domain Runtime 共享的 Provider 与 Agent 无关端口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from .core.messages import AgentMessage


class TranscriptView(Protocol):
    """暴露 canonical Core transcript 的不可变快照。"""

    @property
    def messages(self) -> tuple[AgentMessage, ...]: ...


class NoticeSink(Protocol):
    """发布用户可见通知，但不暴露具体前端。"""

    def emit(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None: ...


class ConversationRunner(Protocol):
    """通过 canonical conversation runtime 执行一个提示。"""

    async def chat(self, prompt: str) -> None: ...


class ModelQuery(Protocol):
    """执行一次 Provider-neutral 且无工具的 side query。"""

    async def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 512,
    ) -> str: ...

    async def complete_messages(
        self,
        *,
        system: str,
        messages: Sequence[AgentMessage],
        max_output_tokens: int = 512,
    ) -> str: ...
