"""与模型供应商无关的 Memory Side Query 契约。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class TextQueryService(Protocol):
    """执行一次无工具、低温度的短文本查询。"""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str: ...


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
