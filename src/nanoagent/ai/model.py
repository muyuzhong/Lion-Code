from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Model:
    id: str
    api: str  # dispatch key: mock / openai-completions / ...
    provider: str  # display/attribution: mock / openai / deepseek
    base_url: str | None = None
    context_window: int = 200_000
    max_tokens: int = 32_768
    reasoning: bool = False
