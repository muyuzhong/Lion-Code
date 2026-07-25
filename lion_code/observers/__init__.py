"""Lion Agent 运行时的事件观察器。

提供终端渲染与 usage 累计两个观察器，均以异步 ``handle`` 方法订阅
``AgentHarness`` 的事件流。观察器只消费事件，不改变运行时状态。
"""

from .terminal import TerminalRenderer
from .usage import UsageObserver, UsageTotals

__all__ = [
    "TerminalRenderer",
    "UsageObserver",
    "UsageTotals",
]
