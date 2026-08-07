"""显式 `/learn` 会话经验沉淀闭环测试。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lion_code import skills
from lion_code.agent import LEARN_META_SKILL_PROMPT
from lion_code.core.messages import AssistantMessage, TextContent, UserMessage
from lion_code.learning_runtime import (
    LEARN_META_SKILL_PROMPT as RUNTIME_LEARN_META_SKILL_PROMPT,
)
from lion_code.learning_runtime import (
    LearningRuntime,
)


class TestCreateSkill(unittest.TestCase):
    def test_create_project_skill_and_reject_overwrite(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                skills._cached_skills = []
                content = "---\nname: learned-flow\ndescription: reusable flow\n---\n\nFollow it."

                result = skills.create_skill("learned-flow", content)

                skill_path = (
                    Path(tmp) / ".claude" / "skills" / "learned-flow" / "SKILL.md"
                )
                self.assertEqual(result, f"Skill created: {skill_path}")
                self.assertEqual(skill_path.read_text(encoding="utf-8"), content)
                self.assertIsNone(skills._cached_skills)
                self.assertEqual(
                    skills.get_skill_by_name("learned-flow").name,
                    "learned-flow",
                )
                self.assertEqual(
                    skills.create_skill("learned-flow", content),
                    "Skill already exists",
                )
                self.assertEqual(
                    skills.create_skill("Invalid_Name", content),
                    "Invalid skill name",
                )
            finally:
                os.chdir(original_cwd)
                skills.reset_skill_cache()


class TestLearnFromSession(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _runtime(messages) -> LearningRuntime:
        host = SimpleNamespace(
            _core_runtime=SimpleNamespace(messages=messages),
            _run_evaluator_query=AsyncMock(),
        )
        return LearningRuntime(host)

    def test_agent_reexports_meta_skill_prompt(self):
        self.assertIs(LEARN_META_SKILL_PROMPT, RUNTIME_LEARN_META_SKILL_PROMPT)

    def test_learning_runtime_import_does_not_import_agent(self):
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import lion_code.learning_runtime; "
                "assert 'lion_code.agent' not in sys.modules",
            ],
            check=True,
        )

    async def test_create_decision_uses_one_meta_skill_call(self):
        runtime = self._runtime(
            (
                UserMessage(content="fix the build"),
                AssistantMessage(
                    model="test",
                    content=[TextContent(text="fixed and verified")],
                ),
            )
        )
        decision = {
            "create": True,
            "reason": "reusable",
            "scope": "project",
            "name": "fix-build",
            "content": "---\nname: fix-build\ndescription: fix build\n---\n\nRun checks.",
        }
        runtime._host._run_evaluator_query = AsyncMock(
            return_value=f"```json\n{json.dumps(decision)}\n```"
        )

        with patch(
            "lion_code.learning_runtime.create_skill", return_value="Skill created"
        ) as create:
            result = await runtime.learn_from_current_session()

        self.assertEqual(result, "Skill created")
        runtime._host._run_evaluator_query.assert_awaited_once()
        system, messages = runtime._host._run_evaluator_query.await_args.args
        self.assertEqual(system, LEARN_META_SKILL_PROMPT)
        self.assertNotIn("ordinary prompt", messages[0]["content"])
        self.assertIn("fix the build", messages[0]["content"])
        self.assertEqual(
            runtime._host._run_evaluator_query.await_args.kwargs["max_tokens"], 4096
        )
        create.assert_called_once_with(
            name="fix-build",
            content=decision["content"],
            scope="project",
        )

    async def test_rejected_decision_does_not_write(self):
        runtime = self._runtime((UserMessage(content="hello"),))
        runtime._host._run_evaluator_query = AsyncMock(
            return_value='{"create": false, "reason": "only small talk"}'
        )

        with patch("lion_code.learning_runtime.create_skill") as create:
            result = await runtime.learn_from_current_session()

        self.assertEqual(result, "不建议沉淀：only small talk")
        create.assert_not_called()

    async def test_invalid_response_does_not_write_skill(self):
        for raw in ("not a JSON decision", '{"create": false'):
            with self.subTest(raw=raw):
                runtime = self._runtime((UserMessage(content="hello"),))
                runtime._host._run_evaluator_query = AsyncMock(return_value=raw)

                with patch("lion_code.learning_runtime.create_skill") as create:
                    with self.assertRaisesRegex(
                        ValueError, "^Invalid Meta-Skill response$"
                    ):
                        await runtime.learn_from_current_session()

                create.assert_not_called()

    async def test_create_decision_missing_required_field_does_not_write(self):
        for missing in ("name", "content", "scope"):
            with self.subTest(missing=missing):
                decision = {
                    "create": True,
                    "name": "fix-build",
                    "content": "---\\nname: fix-build\\n---",
                    "scope": "project",
                }
                del decision[missing]
                runtime = self._runtime((UserMessage(content="hello"),))
                runtime._host._run_evaluator_query = AsyncMock(
                    return_value=json.dumps(decision)
                )

                with patch("lion_code.learning_runtime.create_skill") as create:
                    with self.assertRaisesRegex(
                        ValueError, "^Invalid Meta-Skill response$"
                    ):
                        await runtime.learn_from_current_session()

                create.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
