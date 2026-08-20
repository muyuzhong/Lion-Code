"""Skill 的 TUI 视图模型(vendored 自 tau_coding/skills.py 的子集)。

Lion 的 skill 发现与执行仍在 :mod:`lion_code.capabilities.skill.discovery`(SkillDefinition);
本模块只承载前端所需的不可变视图类型 :class:`Skill`,
应用层负责把 SkillDefinition 桥接为 :class:`Skill`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Skill:
    """A markdown skill resource."""

    name: str
    path: Path
    content: str
    description: str | None = None
