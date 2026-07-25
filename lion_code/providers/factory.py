"""Provider 工厂：根据入参构建 Anthropic 或 OpenAI-compatible 适配器。

本层只负责「按入参选择并构造 provider」，不读取环境变量、不依赖 Agent。
配置解析（凭据与 base_url 的来源）应在外部完成后传入，与 provider 构建保持分离。
"""

from __future__ import annotations

from lion_code.core.provider import ModelProvider

from .anthropic import AnthropicProvider
from .config import AnthropicConfig, OpenAICompatibleConfig
from .openai_compatible import OpenAICompatibleProvider


def create_provider(
    *,
    api_key: str,
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
) -> ModelProvider:
    """按是否提供 ``api_base`` 选择 provider。

    - 给定 ``api_base``：走 OpenAI-compatible 的 ``/chat/completions``；
    - 否则：走 Anthropic Messages API，``base_url`` 缺省为官方端点。
    """
    if api_base:
        return OpenAICompatibleProvider(
            OpenAICompatibleConfig(
                api_key=api_key,
                base_url=api_base.rstrip("/"),
                provider_name="openai-compatible",
                max_tokens=16_384,
            )
        )

    return AnthropicProvider(
        AnthropicConfig(
            api_key=api_key,
            base_url=(anthropic_base_url or "https://api.anthropic.com/v1").rstrip("/"),
        )
    )
