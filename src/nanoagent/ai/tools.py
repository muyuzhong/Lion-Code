from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Tool:
    """The tool wire shape the model sees. execute() lives on agent.AgentTool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
