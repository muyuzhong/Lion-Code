"""``Agent.run()`` 在 Core/Provider 单路径上的结构化结果契约。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.fakes import FakeProvider
from full_agent import FullAgentHarness, build_full_agent_harness

from lion_code.core import AssistantMessage, TextContent, ToolCall, Usage
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent
from lion_code.runtime.agent import AgentRunResult
from lion_code.session_runtime import SessionRepository


def _stop_event(
    text: str = "done",
    *,
    usage: Usage | None = None,
) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
            usage=usage or Usage(),
        ),
    )


def _tool_use_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[
                ToolCall(
                    id="t1",
                    name="read_file",
                    arguments={"file_path": "README.md"},
                )
            ],
            stop_reason="toolUse",
        ),
    )


def _error_event(message: str) -> AssistantErrorEvent:
    return AssistantErrorEvent(
        reason="error",
        error=AssistantMessage(
            model="fake",
            content=[],
            stop_reason="error",
            error_message=message,
        ),
    )


class _HangingProvider(FakeProvider):
    async def _gen(self, signal):
        await asyncio.sleep(30)
        if False:
            yield None


class _CancellationAwareProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__([])
        self.entered = asyncio.Event()

    async def _gen(self, signal):
        if signal is None:
            raise AssertionError("运行时必须把取消状态传给 Provider")
        self.entered.set()
        while not signal.is_cancelled():
            await asyncio.sleep(0)
        yield AssistantErrorEvent(
            reason="aborted",
            error=AssistantMessage(model="fake", stop_reason="aborted"),
        )


class TestAgentRun(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._session_repository = SessionRepository(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def _agent(self, provider: FakeProvider, **kwargs) -> FullAgentHarness:
        with patch("full_agent.create_provider", return_value=provider):
            harness = build_full_agent_harness(
                api_key="test-key",
                is_sub_agent=True,
                session_repository=self._session_repository,
                **kwargs,
            )
        return harness

    async def test_completed_run_returns_structured_core_result(self) -> None:
        provider = FakeProvider([_stop_event(usage=Usage(input=12, output=7))])
        agent = self._agent(provider)

        result = await agent.agent.run("hi")
        await agent.agent.close()

        self.assertIsInstance(result, AgentRunResult)
        self.assertEqual(result.stop_reason, "completed")
        self.assertEqual(result.final_text, "done")
        self.assertEqual(result.turns, 0)
        self.assertIsNone(result.error)
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output_tokens, 7)
        self.assertEqual(result.cache_read_tokens, 0)
        self.assertTrue(result.session_id)
        self.assertGreaterEqual(result.wall_time_seconds, 0.0)
        self.assertGreaterEqual(result.cost_usd, 0.0)

    async def test_run_returns_only_the_current_invocation_usage_delta(self) -> None:
        provider = FakeProvider(
            [
                _stop_event(usage=Usage(input=12, output=7, cache_read=4)),
                _stop_event(usage=Usage(input=5, output=2, cache_read=3)),
            ]
        )
        agent = self._agent(provider)

        first = await agent.agent.run("first")
        second = await agent.agent.run("second")
        await agent.agent.close()

        self.assertEqual(
            (first.input_tokens, first.output_tokens, first.cache_read_tokens),
            (12, 7, 4),
        )
        self.assertEqual(
            (second.input_tokens, second.output_tokens, second.cache_read_tokens),
            (5, 2, 3),
        )
        self.assertAlmostEqual(second.cost_usd, 45.9 / 1_000_000)

    async def test_run_once_returns_only_the_current_invocation_usage_delta(
        self,
    ) -> None:
        provider = FakeProvider(
            [
                _stop_event(usage=Usage(input=12, output=7)),
                _stop_event(usage=Usage(input=5, output=2)),
            ]
        )
        agent = self._agent(provider)

        first = await agent.agent.run_once("first")
        second = await agent.agent.run_once("second")
        await agent.agent.close()

        self.assertEqual(first["tokens"], {"input": 12, "output": 7})
        self.assertEqual(second["tokens"], {"input": 5, "output": 2})

    async def test_max_turns_records_canonical_tool_result(self) -> None:
        agent = self._agent(FakeProvider([_tool_use_event()]), max_turns=1)
        encoding_error = UnicodeEncodeError(
            "gbk", "ℹ", 0, 1, "illegal multibyte sequence"
        )

        with patch("full_agent.print_info", side_effect=encoding_error):
            result = await agent.agent.run("do something")
        await agent.agent.close()

        self.assertEqual(result.stop_reason, "max_turns")
        self.assertEqual(result.turns, 1)
        self.assertEqual(
            [message.role for message in agent.agent.messages],
            ["user", "assistant", "toolResult"],
        )
        self.assertIn("Turn limit reached", agent.agent.messages[-1].text)

    async def test_provider_error_is_returned_without_raising(self) -> None:
        agent = self._agent(FakeProvider([_error_event("boom")]))

        result = await agent.agent.run("hi")
        await agent.agent.close()

        self.assertEqual(result.stop_reason, "model_error")
        self.assertEqual(result.error, "boom")
        self.assertEqual(result.final_text, "")

    async def test_run_does_not_reuse_previous_assistant_text(self) -> None:
        agent = self._agent(FakeProvider([_stop_event("previous")]))
        first = await agent.agent.run("first")

        agent.agent.configure_provider(api_key="")
        second = await agent.agent.run("second")
        await agent.agent.close()

        self.assertEqual(first.final_text, "previous")
        # R2：未配置凭证时不再静默返回，注入含 API 未配置说明的 error 消息。
        self.assertIn("API 未配置", second.final_text)
        self.assertNotEqual(second.final_text, "previous")

    async def test_run_once_does_not_reuse_previous_assistant_text(self) -> None:
        agent = self._agent(FakeProvider([_stop_event("previous")]))
        first = await agent.agent.run_once("first")

        agent.agent.configure_provider(api_key="")
        second = await agent.agent.run_once("second")
        await agent.agent.close()

        self.assertEqual(first["text"], "previous")
        # 同 test_run：未配置时返回可见的错误说明，而非空文本。
        self.assertIn("API 未配置", second["text"])
        self.assertNotEqual(second["text"], "previous")

    async def test_timeout_cancels_core_provider_wait(self) -> None:
        agent = self._agent(_HangingProvider([]))

        result = await agent.agent.run("hi", timeout=0.01)
        await agent.agent.close()

        self.assertEqual(result.stop_reason, "timeout")
        self.assertIsNotNone(result.error)
        self.assertTrue(agent.agent.cancelled)

    async def test_explicit_abort_keeps_aborted_stop_reason(self) -> None:
        provider = _CancellationAwareProvider()
        agent = self._agent(provider)

        task = asyncio.create_task(agent.agent.run("hi"))
        await provider.entered.wait()
        agent.agent.cancel()
        result = await asyncio.wait_for(task, timeout=1)
        await agent.agent.close()

        self.assertEqual(result.stop_reason, "aborted")
        self.assertTrue(agent.agent.cancelled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
