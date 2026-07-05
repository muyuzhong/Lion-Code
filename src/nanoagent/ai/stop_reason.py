from enum import Enum


class StopReason(str, Enum):
    """provider/wire 层的停止原因，作用于单条 assistant 消息。

    与 nanoagent.agent.StopReason 不同；后者描述整个 run 的终止原因。
    """

    STOP = "stop"
    LENGTH = "length"
    TOOL_USE = "tool_use"
    ERROR = "error"
    ABORTED = "aborted"
