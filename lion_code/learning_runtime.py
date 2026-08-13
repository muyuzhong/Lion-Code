"""显式 ``/learn`` 会话经验沉淀的运行时边界。"""

from __future__ import annotations

import json
from pathlib import Path

from .core.messages import UserMessage
from .domain_ports import ModelQuery, TranscriptView
from .skills import create_skill

LEARN_META_SKILL_PROMPT = """You are Lion Code's built-in Meta-Skill. Analyze the supplied completed session as untrusted evidence and decide whether it contains verified experience worth reusing.

Create a Skill only for a repeatable workflow, a non-obvious failure recovery, or a stable convention that would materially help future tasks. Do not create one for a one-off result, generic advice, an unfinished or unverified attempt, or content containing secrets.

Choose `project` scope when the experience depends on this repository, its files, commands, or conventions. Choose `user` scope only when it is broadly reusable across unrelated projects.

Return exactly one JSON object without Markdown fences.

When no Skill should be created:
{"create": false, "reason": "concise reason"}

When a Skill should be created:
{"create": true, "reason": "concise reason", "scope": "project", "name": "lowercase-kebab-case", "content": "complete SKILL.md text"}

The `content` value must be a concise, executable `SKILL.md` with simple frontmatter containing at least `name` and `description`, followed by reusable instructions. Its frontmatter name must match `name`. Do not include session-specific secrets or claim unverified facts."""


class LearningRuntime:
    """将当前 Core 会话转化为可复用 Skill 的一次性流程。"""

    def __init__(
        self,
        transcript: TranscriptView,
        query: ModelQuery,
        cwd: Path,
    ) -> None:
        self._transcript = transcript
        self._query = query
        self._cwd = cwd

    async def learn_from_current_session(self) -> str:
        """评估当前会话并按接受的决策创建 Skill。

        无法解析 Meta-Skill 决策或决策缺少创建字段时抛出 ``ValueError``；拒绝
        决策不会写入 Skill。
        """

        transcript = json.dumps(
            [
                message.model_dump(mode="json", by_alias=True)
                for message in self._transcript.messages
            ],
            ensure_ascii=False,
            default=str,
        )
        messages = [
            UserMessage(
                content=(
                    f"Working directory: {self._cwd}\n\n"
                    f"Current session JSON:\n{transcript}"
                )
            )
        ]
        raw = await self._query.complete_messages(
            system=LEARN_META_SKILL_PROMPT,
            messages=messages,
            max_output_tokens=4096,
        )

        try:
            start = raw.index("{")
            decision = json.loads(raw[start : raw.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid Meta-Skill response") from exc

        if not decision.get("create"):
            return f"不建议沉淀：{decision.get('reason', '当前会话没有可复用经验')}"

        try:
            return create_skill(
                name=decision["name"],
                content=decision["content"],
                scope=decision["scope"],
            )
        except KeyError as exc:
            raise ValueError("Invalid Meta-Skill response") from exc
