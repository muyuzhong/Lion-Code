"""基于 live Provider 的 Domain ModelQuery 实现。"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .core.messages import AgentMessage, UserMessage
from .core.provider import ModelProvider
from .providers.oneshot import complete_text


class ModelQueryUnavailableError(RuntimeError):
    """API 尚未配置时拒绝 side query。"""


class ProviderModelQuery:
    """每次 side query 都重新解析当前 Provider 与 model。

    Callable 使适配器跨 ProviderManager 替换事务保持 live，同时不向 Domain
    暴露 readiness 或 Provider 实现细节。
    """

    def __init__(
        self,
        *,
        provider: Callable[[], ModelProvider],
        model: Callable[[], str],
        available: Callable[[], bool],
    ) -> None:
        self._provider = provider
        self._model = model
        self._available = available

    async def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 512,
    ) -> str:
        del max_output_tokens
        return await self.complete_messages(
            system=system,
            messages=[UserMessage(content=user)],
        )

    async def complete_messages(
        self,
        *,
        system: str,
        messages: Sequence[AgentMessage],
        max_output_tokens: int = 512,
    ) -> str:
        del max_output_tokens
        if not self._available():
            raise ModelQueryUnavailableError("API is not configured")
        return await complete_text(
            self._provider(),
            model=self._model(),
            system=system,
            messages=list(messages),
        )
