"""Prompt template 视图类型(vendored 自 tau_coding/prompt_templates.py 的子集)。

阶段 2 只提供数据类型;发现与展开逻辑按迁移计划在阶段 4 落地。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A markdown prompt template resource."""

    name: str
    path: Path
    content: str
    description: str | None = None
