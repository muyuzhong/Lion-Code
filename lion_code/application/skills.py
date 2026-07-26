"""Skill 的 TUI 视图模型(vendored 自 tau_coding/skills.py 的子集)。

Lion 的 skill 发现与执行仍在 :mod:`lion_code.skills`(SkillDefinition);
本模块只承载前端与 prompt 展开所需的不可变视图类型与调用格式,
应用层负责把 SkillDefinition 桥接为 :class:`Skill`。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .resources import ResourceError


@dataclass(frozen=True, slots=True)
class Skill:
    """A markdown skill resource."""

    name: str
    path: Path
    content: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SkillInvocation:
    """Parsed expanded skill invocation message."""

    name: str
    location: str
    content: str
    additional_instructions: str | None = None


def expand_skill_command(text: str, skills: Sequence[Skill]) -> str | None:
    """Expand `/skill:name` prompt text, or return None for non-skill text."""
    stripped = text.strip()
    if not stripped.startswith("/skill:"):
        return None

    command, separator, request = stripped.partition(" ")
    name = command.removeprefix("/skill:").strip()
    if not name:
        raise ResourceError("Skill command must include a skill name")

    skill_by_name = {skill.name: skill for skill in skills}
    skill = skill_by_name.get(name)
    if skill is None:
        raise ResourceError(f"Unknown skill: {name}")

    additional_instructions = request.strip() if separator else None
    return format_skill_invocation(skill, additional_instructions)


def format_skill_invocation(
    skill: Skill,
    additional_instructions: str | None = None,
) -> str:
    """Format a full skill invocation prompt."""
    skill_block = (
        f'<skill name="{skill.name}" location="{skill.path}">\n'
        f"References are relative to {skill.path.parent}.\n\n"
        f"{skill.content.strip()}\n"
        "</skill>"
    )
    if additional_instructions and additional_instructions.strip():
        return f"{skill_block}\n\n{additional_instructions.strip()}"
    return skill_block


def parse_skill_invocation(text: str) -> SkillInvocation | None:
    """Parse the expanded skill invocation message format."""
    match = re.match(
        r'^<skill name="([^"]+)" location="([^"]+)">\n([\s\S]*?)\n</skill>(?:\n\n([\s\S]+))?$',
        text,
    )
    if match is None:
        return None
    name, location, content, additional_instructions = match.groups()
    return SkillInvocation(
        name=name,
        location=location,
        content=content,
        additional_instructions=additional_instructions,
    )
