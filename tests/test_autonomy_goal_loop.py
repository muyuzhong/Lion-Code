"""/goal 与 /loop 协调的行为特征测试。

迁移到 ``autonomy_runtime`` 前先刻画当前 ``Agent`` 行为;迁移后这些测试针对公共
API(``Agent.set_goal``/``pursue_goal``/``run_loop`` 等,经委托保留)仍应通过。
所有模型调用与睡眠都被 stub,不访问网络、不真实等待。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from lion_code.agent import Agent

    HAVE_AGENT = True
except Exception:
    HAVE_AGENT = False


def _make_agent(**kwargs) -> Agent:
    """构造真实 Agent(经 __init__),再 stub 掉模型与通知。"""
    agent = Agent(
        api_key="test-key",
        permission_mode=kwargs.get("permission_mode", "default"),
        max_cost_usd=kwargs.get("max_cost_usd"),
        max_turns=kwargs.get("max_turns"),
    )
    agent._emit_notice = lambda *a, **k: None
    agent.chat = AsyncMock()
    return agent


@unittest.skipUnless(HAVE_AGENT, "Agent 不可导入")
class TestGoalPursuit(unittest.IsolatedAsyncioTestCase):
    async def test_no_active_goal_returns_without_chatting(self) -> None:
        agent = _make_agent()
        await agent.pursue_goal("directive")
        agent.chat.assert_not_awaited()

    async def test_goal_met_on_first_eval_clears_active_goal(self) -> None:
        agent = _make_agent()
        agent._run_evaluator_query = AsyncMock(
            return_value='{"ok": true, "reason": "tests green"}'
        )
        directive = agent.set_goal("build passes")
        await agent.pursue_goal(directive)

        agent.chat.assert_awaited_once_with(directive)
        agent._run_evaluator_query.assert_awaited_once()
        self.assertIsNone(agent.active_goal)

    async def test_goal_not_met_then_met_chats_keep_working(self) -> None:
        agent = _make_agent()
        agent._run_evaluator_query = AsyncMock(
            side_effect=[
                '{"ok": false, "reason": "not yet"}',
                '{"ok": true, "reason": "done"}',
            ]
        )
        directive = agent.set_goal("build passes")
        await agent.pursue_goal(directive)

        self.assertEqual(agent.chat.await_count, 2)
        self.assertIsNone(agent.active_goal)

    async def test_goal_impossible_stops_without_keep_working(self) -> None:
        agent = _make_agent()
        agent._run_evaluator_query = AsyncMock(
            return_value='{"ok": false, "impossible": true, "reason": "nope"}'
        )
        directive = agent.set_goal("build passes")
        await agent.pursue_goal(directive)

        agent.chat.assert_awaited_once_with(directive)
        self.assertIsNone(agent.active_goal)

    async def test_goal_budget_exceeded_stops(self) -> None:
        agent = _make_agent(max_cost_usd=0.0)
        agent._run_evaluator_query = AsyncMock(
            return_value='{"ok": false, "reason": "not yet"}'
        )
        directive = agent.set_goal("build passes")
        await agent.pursue_goal(directive)

        agent.chat.assert_awaited_once_with(directive)
        self.assertIsNone(agent.active_goal)

    async def test_stop_goal_interrupts_pursuit(self) -> None:
        agent = _make_agent()
        agent._run_evaluator_query = AsyncMock(
            return_value='{"ok": false, "reason": "not yet"}'
        )
        directive = agent.set_goal("build passes")

        async def chat_then_stop(_msg: str) -> None:
            # 首轮 chat 后请求停止,模拟用户 Ctrl+C。
            agent.stop_goal()

        agent.chat = AsyncMock(side_effect=chat_then_stop)
        await agent.pursue_goal(directive)

        self.assertIsNone(agent.active_goal)


@unittest.skipUnless(HAVE_AGENT, "Agent 不可导入")
class TestLoopRun(unittest.IsolatedAsyncioTestCase):
    async def test_empty_loop_input_emits_error_without_chatting(self) -> None:
        agent = _make_agent()
        await agent.run_loop("")
        agent.chat.assert_not_awaited()

    async def test_interval_loop_stops_at_max_turns_before_sleep(self) -> None:
        # max_turns=1:一轮 chat 后即触达 tick 上限,不进入睡眠。
        agent = _make_agent(max_turns=1)
        await agent.run_loop("5s do the task")
        agent.chat.assert_awaited_once()

    async def test_interval_loop_runs_two_ticks_then_max_turns(self) -> None:
        agent = _make_agent(max_turns=2)
        self._stub_sleep(agent, interrupted=False)
        await agent.run_loop("1s do the task")
        self.assertEqual(agent.chat.await_count, 2)

    async def test_dynamic_loop_converges_when_no_wakeup_scheduled(self) -> None:
        agent = _make_agent()
        # chat 是 AsyncMock,不会写 pending_wakeup -> 一轮后收敛。
        await agent.run_loop("do the task")
        agent.chat.assert_awaited_once()

    @staticmethod
    def _stub_sleep(agent: Agent, *, interrupted: bool) -> None:
        mock = AsyncMock(return_value=interrupted)
        # 迁移前 _interruptible_sleep 在 Agent;迁移后在 agent._autonomy。两层都 stub,
        # 保证迁移前后测试一致。
        agent._interruptible_sleep = mock
        autonomy = getattr(agent, "_autonomy", None)
        if autonomy is not None:
            autonomy._interruptible_sleep = mock


if __name__ == "__main__":
    unittest.main(verbosity=2)
