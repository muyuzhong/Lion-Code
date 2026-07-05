from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StreamOptions:
    """模型流式调用的注入端口。

    harness 决定 key、base_url、采样参数和取消信号；框架不选择 provider 或密钥。
    `signal` 采用 duck type（只读取 `.aborted`），避免 `ai` 反向依赖 `agent`。
    """

    api_key: str | None = None
    base_url: str | None = None
    signal: Any = None
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning: str | None = None

    def __post_init__(self) -> None:
        if self.max_tokens is not None and self.max_tokens < 0:
            raise ValueError("max_tokens must be non-negative")
