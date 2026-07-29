"""与模型供应商无关的 Memory Side Query 契约。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from lion_code.core.messages import UserMessage
from lion_code.core.provider import ModelProvider
from lion_code.providers.oneshot import complete_text


class TextQueryService(Protocol):
    """执行一次无工具的短文本查询。"""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str: ...


class ProviderTextQueryService:
    """基于 Core Provider 的 Side Query 实现，不依赖供应商 SDK。

    ``max_output_tokens`` 由 Provider 配置统一决定,协议层不支持逐调用
    覆盖,参数仅为满足 TextQueryService 契约。
    """

    def __init__(
        self,
        *,
        provider: ModelProvider,
        model: str | Callable[[], str],
    ) -> None:
        self._provider = provider
        self._model = model

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str:
        del max_output_tokens
        model = self._model() if callable(self._model) else self._model
        return await complete_text(
            self._provider,
            model=model,
            system=system,
            messages=[UserMessage(content=user)],
        )
