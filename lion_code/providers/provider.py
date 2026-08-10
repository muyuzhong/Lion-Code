"""Lion 模型适配器实现的 Provider 契约。

仅从 :mod:`lion_code.core.provider` 重新导出 ``ModelProvider``，不在
Provider 包中保留第二个取消类型入口。
"""

from lion_code.core.provider import ModelProvider

__all__ = ["ModelProvider"]
