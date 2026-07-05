from __future__ import annotations

import copy
from dataclasses import dataclass

from nanoagent.ai.types import JSONValue


@dataclass
class Tool:
    """模型可见的工具 wire 形状；实际 execute() 位于 agent.AgentTool。"""

    name: str
    description: str
    parameters: dict[str, JSONValue]  # JSON Schema。

    def __post_init__(self) -> None:
        # 隔离输入 schema，避免调用方后续修改污染 provider 可见工具定义。
        self.parameters = copy.deepcopy(self.parameters)
