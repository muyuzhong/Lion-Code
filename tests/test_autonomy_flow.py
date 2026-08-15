"""两阶段 Auto Mode 分类器的控制流测试。

测试会替换分类器查询，不访问网络；如果未安装模型 SDK，则自动跳过。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from lion_code.agent import Agent

    HAVE_AGENT = True
except Exception:
    HAVE_AGENT = False

HAVE_DEPS = HAVE_AGENT and (_ROOT / "assets" / "auto-mode-rules.json").is_file()


def _make_agent(responses):
    agent = Agent(api_key="test-key")
    calls = {"count": 0}

    async def stub(*, system, user, max_output_tokens):
        del system, user, max_output_tokens
        index = calls["count"]
        calls["count"] += 1
        if index < len(responses):
            return responses[index]
        return "<block>yes</block><reason>no canned response</reason>"

    agent._autonomy._query.complete_text = stub
    return agent, calls


@unittest.skipUnless(HAVE_AGENT, "Agent 不可导入")
class TestAutoModeConfirmationRefresh(unittest.TestCase):
    def test_late_confirm_callback_is_used_by_fallback(self):
        agent, _ = _make_agent([])
        agent.set_confirm_fn(AsyncMock(return_value=True))

        result = agent._autonomy._auto_fallback("blocked")

        self.assertEqual(result["action"], "confirm")


@unittest.skipUnless(HAVE_AGENT, "Agent 不可导入")
class TestAutoModeUnavailableFallback(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_query_uses_live_confirm_without_counting_denial(self):
        from lion_code.model_query import ModelQueryUnavailableError

        agent, _ = _make_agent([])
        agent.set_confirm_fn(AsyncMock(return_value=True))
        agent._autonomy._query.complete_text = AsyncMock(
            side_effect=ModelQueryUnavailableError("not configured")
        )

        with (
            patch(
                "lion_code.autonomy_runtime.load_auto_mode_rules",
                return_value={"suffix_stage1": "stage one"},
            ),
            patch(
                "lion_code.autonomy_runtime.build_classifier_system", return_value="sys"
            ),
            patch("lion_code.autonomy_runtime.load_claude_md", return_value=""),
            patch(
                "lion_code.autonomy_runtime.classifier_user_message",
                return_value="input",
            ),
        ):
            result = await agent._classify_tool_call(
                "run_shell",
                {"command": "echo hi"},
            )

        self.assertEqual(result["action"], "confirm")
        self.assertEqual(agent.auto_consecutive_denials, 0)
        self.assertEqual(agent.auto_total_denials, 0)


@unittest.skipUnless(HAVE_DEPS, "Auto Mode 规则文件未保留")
class TestAutoModeFlow(unittest.IsolatedAsyncioTestCase):
    async def test_stage_one_allow(self):
        agent, calls = _make_agent(["<block>no</block>"])
        result = await agent._classify_tool_call("run_shell", {"command": "echo hi"})
        self.assertEqual(result["action"], "allow")
        self.assertEqual(calls["count"], 1)

    async def test_stage_two_allow_after_stage_one_block(self):
        agent, calls = _make_agent(
            [
                "<block>yes</block><reason>needs review</reason>",
                "<block>no</block>",
            ]
        )
        result = await agent._classify_tool_call("run_shell", {"command": "echo hi"})
        self.assertEqual(result["action"], "allow")
        self.assertEqual(calls["count"], 2)

    async def test_stage_two_block_counts_once(self):
        agent, calls = _make_agent(
            [
                "<block>yes</block><reason>unsafe</reason>",
                "<block>yes</block><reason>still unsafe</reason>",
            ]
        )
        result = await agent._classify_tool_call("run_shell", {"command": "echo hi"})
        self.assertEqual(result["action"], "deny")
        self.assertIn("[Auto Mode]", result["message"])
        self.assertEqual(agent.auto_consecutive_denials, 1)
        self.assertEqual(calls["count"], 2)

    async def test_unparseable_stage_two_blocks(self):
        agent, _ = _make_agent(
            [
                "<block>yes</block><reason>needs review</reason>",
                "not a verdict",
            ]
        )
        result = await agent._classify_tool_call("run_shell", {"command": "echo hi"})
        self.assertEqual(result["action"], "deny")

    async def test_read_only_tool_skips_classifier(self):
        agent, calls = _make_agent(["<block>yes</block><reason>unused</reason>"])
        result = await agent._classify_tool_call("read_file", {"file_path": "x"})
        self.assertEqual(result["action"], "allow")
        self.assertEqual(calls["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
