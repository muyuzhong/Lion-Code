from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Model:
    """模型描述，不携带密钥或默认选择策略。"""

    id: str
    api: str  # provider registry 的分发键，例如 mock / openai-completions。
    provider: str  # 展示和归属用名称，例如 mock / openai / deepseek。
    base_url: str | None = None
    context_window: int = 200_000
    max_tokens: int = 32_768
    reasoning: bool = False
