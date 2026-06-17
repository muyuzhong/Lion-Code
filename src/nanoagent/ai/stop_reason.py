from enum import Enum


class StopReason(str, Enum):
    """Wire-level stop reason (per assistant message).

    Distinct from nanoagent.agent.StopReason (run-level loop termination).
    """

    STOP = "stop"
    LENGTH = "length"
    TOOL_USE = "tool_use"
    ERROR = "error"
    ABORTED = "aborted"
