"""Model-limit discovery with a static compatibility fallback."""

from __future__ import annotations

from types import MappingProxyType

from lion_code.core.provider import ModelProvider
from lion_code.providers.model_limits import ModelLimitsProvider, RuntimeModelLimits


DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
DEFAULT_OUTPUT_RESERVE_TOKENS = 20_000
MODEL_CONTEXT_WINDOWS = MappingProxyType(
    {
        "claude-opus-4-6": 200_000,
        "claude-sonnet-4-6": 200_000,
        "claude-sonnet-4-20250514": 200_000,
        "claude-haiku-4-5-20251001": 200_000,
        "claude-opus-4-20250514": 200_000,
        "gpt-4o": 128_000,
        "gpt-4o-mini": 128_000,
    }
)


def fallback_context_window(model: str) -> int:
    """Return the legacy static window until a provider advertises live limits."""

    return MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW_TOKENS)


def fallback_model_limits(model: str) -> RuntimeModelLimits:
    return RuntimeModelLimits(
        context_window=fallback_context_window(model),
        max_output_tokens=DEFAULT_OUTPUT_RESERVE_TOKENS,
    )


def effective_window_tokens(limits: RuntimeModelLimits) -> int:
    """Reserve the advertised maximum output from the usable provider window."""

    reserve = limits.max_output_tokens or 0
    return max(1, limits.effective_context_window - reserve)


class ModelLimitsResolver:
    """Prefer optional provider discovery and otherwise preserve legacy limits."""

    async def resolve(
        self,
        provider: ModelProvider,
        model: str,
    ) -> RuntimeModelLimits:
        if isinstance(provider, ModelLimitsProvider):
            discovered = await provider.discover_model_limits(model)
            if discovered is not None:
                return discovered
        return fallback_model_limits(model)
