"""通过 ModelProvider 生成上下文摘要的供应商无关契约。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from lion_code.core.messages import AgentMessage, UserMessage
from lion_code.core.provider import ModelProvider
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent


SUMMARY_SYSTEM_PROMPT = (
    "You summarize coding-agent conversations. Preserve decisions, constraints, "
    "file paths, commands, unfinished work, and facts needed to continue. Be concise."
)
SUMMARY_USER_PROMPT = (
    "Summarize the conversation above for the next model call. Preserve concrete "
    "decisions, file paths, commands, failures, and remaining work."
)


class ContextCompactor(Protocol):
    """把一段 canonical 历史压缩为可继续工作的文本摘要。"""

    async def summarize(self, messages: tuple[AgentMessage, ...]) -> str:
        ...


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

    async def summarize(self, messages: tuple[AgentMessage, ...]) -> str:
        projected = [message.model_copy(deep=True) for message in messages]
        projected.append(UserMessage(content=SUMMARY_USER_PROMPT))
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
