"""Lion 模型适配器实现的 Provider 契约。

仅从 :mod:`lion_code.core.provider` 重新导出 ``CancellationToken`` 与
``ModelProvider``，使 provider 实现可经由 ``from .provider import ...``
取得契约，而不引入第二套类型定义。
"""

from lion_code.core.provider import (
    CancellationToken,
    ModelProvider,
)

__all__ = [
    "CancellationToken",
    "ModelProvider",
]
