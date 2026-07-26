from __future__ import annotations

import pytest

from lion_code.context import (
    ModelLimitsResolver,
    effective_window_tokens,
    fallback_context_window,
)
from lion_code.providers import RuntimeModelLimits


class _StaticProvider:
    async def discover_model_limits(self, model: str) -> RuntimeModelLimits | None:
        assert model == "live"
        return RuntimeModelLimits(context_window=128_000, max_output_tokens=8_000)


class _PlainProvider:
    pass


@pytest.mark.asyncio
async def test_resolver_prefers_provider_limits() -> None:
    limits = await ModelLimitsResolver().resolve(_StaticProvider(), "live")

    assert limits.context_window == 128_000
    assert effective_window_tokens(limits) == 120_000


@pytest.mark.asyncio
async def test_resolver_falls_back_to_static_limits() -> None:
    limits = await ModelLimitsResolver().resolve(_PlainProvider(), "gpt-4o")

    assert fallback_context_window("gpt-4o") == 128_000
    assert effective_window_tokens(limits) == 108_000
