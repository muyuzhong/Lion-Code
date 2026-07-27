"""Provider 工厂：根据入参构建 Anthropic 或 OpenAI-compatible 适配器。

本层只负责「按入参选择并构造 provider」，不读取环境变量、不依赖 Agent。
配置解析（凭证与 base_url 的来源）应在外部完成后传入，与 provider 构建保持分离。

``thinking_level`` 把应用层档位(off/minimal/low/medium/high/xhigh)翻译为各
provider 的 thinking 参数(见 :mod:`lion_code.providers.thinking`);``None``
表示不注入 thinking,保持 provider 默认(等价于不开启 thinking)。
"""

from __future__ import annotations

from lion_code.core.provider import ModelProvider

from .anthropic import AnthropicProvider
from .config import AnthropicConfig, OpenAICompatibleConfig
from .openai_compatible import OpenAICompatibleProvider
from .thinking import (
    ThinkingLevel,
    anthropic_budget_tokens_for_level,
    normalize_thinking_level,
    openai_reasoning_effort_for_level,
)


def create_provider(
    *,
    api_key: str,
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    thinking_level: ThinkingLevel | str | None = None,
) -> ModelProvider:
    """按是否提供 ``api_base`` 选择 provider。

    - 给定 ``api_base``：走 OpenAI-compatible 的 ``/chat/completions``；
    - 否则：走 Anthropic Messages API，``base_url`` 缺省为官方端点。

    ``thinking_level`` 为 ``None`` 时不注入 thinking(保持 provider 默认);
    否则按档位填入 Anthropic ``budget_tokens`` 或 OpenAI ``reasoning_effort``。
    """
    if api_base:
        return OpenAICompatibleProvider(
            OpenAICompatibleConfig(
                api_key=api_key,
                base_url=api_base.rstrip("/"),
                provider_name="openai-compatible",
                max_tokens=16_384,
                **_openai_thinking_kwargs(thinking_level),
            )
        )

    return AnthropicProvider(
        AnthropicConfig(
            api_key=api_key,
            base_url=(anthropic_base_url or "https://api.anthropic.com/v1").rstrip("/"),
            **_anthropic_thinking_kwargs(thinking_level),
        )
    )


def _anthropic_thinking_kwargs(
    level: ThinkingLevel | str | None,
) -> dict[str, object]:
    """档位 -> AnthropicConfig 的 thinking 字段。

    ``None``:不注入(默认 mode="budget"、budget=None -> 不开 thinking);
    ``off``:显式 ``thinking_mode="disabled"``;
    其余:``thinking_budget_tokens`` 取档位映射值(mode 留默认 "budget" -> enabled)。
    """
    if level is None:
        return {}
    normalized = normalize_thinking_level(level)
    if normalized == "off":
        return {"thinking_mode": "disabled"}
    return {"thinking_budget_tokens": anthropic_budget_tokens_for_level(normalized)}


def _openai_thinking_kwargs(
    level: ThinkingLevel | str | None,
) -> dict[str, object]:
    """档位 -> OpenAICompatibleConfig 的 reasoning_effort 字段。

    ``None``:不注入(默认 reasoning_effort=None -> 不开 reasoning);
    其余(含 ``off``):设为 ``reasoning_effort``(off -> "none" -> 不开 reasoning)。
    """
    if level is None:
        return {}
    normalized = normalize_thinking_level(level)
    return {"reasoning_effort": openai_reasoning_effort_for_level(normalized)}
