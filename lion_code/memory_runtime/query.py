"""与模型供应商无关的 Memory Side Query 契约。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from lion_code.core.messages import UserMessage
from lion_code.core.provider import ModelProvider
from lion_code.providers.oneshot import complete_text


class TextQueryService(Protocol):
    """执行一次无工具、低温度的短文本查询。"""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str: ...


class ProviderTextQueryService:
    """基于 Core Provider 的 Side Query 实现(httpx 直连,无 SDK)。

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


class LegacySdkTextQueryService:
    """用现有 SDK Client 适配 Side Query，供旧客户端迁移期复用。"""

    def __init__(
        self,
        *,
        openai_client: Any = None,
        anthropic_client: Any = None,
        model: str | Callable[[], str],
    ) -> None:
        self._openai = openai_client
        self._anthropic = anthropic_client
        self._model = model

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str:
        model = self._model() if callable(self._model) else self._model
        if self._anthropic is not None:
            response = await self._anthropic.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_output_tokens,
                temperature=0,
            )
            return "".join(
                block.text
                for block in response.content
                if block.type == "text"
            )

        if self._openai is not None:
            response = await self._openai.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_output_tokens,
                temperature=0,
            )
            if not response.choices:
                return ""
            return response.choices[0].message.content or ""

        raise RuntimeError("No model available for memory query")
