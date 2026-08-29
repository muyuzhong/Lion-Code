"""Environment-based provider configuration helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from lion_code.core.types import JSONValue

DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES = 2
DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    """Configuration for an OpenAI-compatible chat completions endpoint."""

    api_key: str
    base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL
    headers: Mapping[str, str] | None = None
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    api: str = "openai-completions"
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    provider_name: str = "OpenAI-compatible provider"


@dataclass(frozen=True, slots=True)
class AnthropicConfig:
    """Configuration for Anthropic's Messages API."""

    api_key: str
    base_url: str = DEFAULT_ANTHROPIC_BASE_URL
    headers: Mapping[str, str] | None = None
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    max_tokens: int | None = None
    thinking_budget_tokens: int | None = None
    thinking_effort: str | None = None
    thinking_mode: str = "budget"
    provider_name: str = "Anthropic"
