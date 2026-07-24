"""agent.run() 结构化运行入口测试。

通过替换 _call_anthropic_stream / _call_openai_stream 驱动真实轮次循环，
验证 stop_reason、turns、token、final_text 等结构化字段。
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lion_code.agent import Agent, AgentRunResult


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str = "fake_tool", tool_id: str = "t1", inp: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=inp or {})


def _anthropic_response(blocks, *, input_tokens=10, output_tokens=5, cache_read=0, cache_creation=0):
    return SimpleNamespace(
        content=list(blocks),
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_creation,
        ),
    )


def _anthropic_stream(responses):
    """返回一个替换 _call_anthropic_stream 的协程，按顺序消费 responses，并模拟文本下发。"""

    async def _stream(self, on_tool_block_complete=None):
        resp = responses.pop(0)
        first_text = True
        for block in resp.content:
            if block.type == "text":
                if first_text:
                    self._emit_text("\n")
                    first_text = False
                self._emit_text(block.text)
            elif block.type == "tool_use" and on_tool_block_complete:
                on_tool_block_complete(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        return resp

    return _stream


class TestAgentRun(unittest.IsolatedAsyncioTestCase):
    async def test_run_completed_returns_structured_result(self):
        agent = Agent(api_key="test-key", is_sub_agent=True)
        responses = [_anthropic_response([_text_block("done")], input_tokens=12, output_tokens=7)]
        with patch.object(Agent, "_call_anthropic_stream", new=_anthropic_stream(responses)):
            result = await agent.run("hi")
        await agent.close()

        self.assertIsInstance(result, AgentRunResult)
        self.assertEqual(result.stop_reason, "completed")
        self.assertIn("done", result.final_text)
        self.assertEqual(result.turns, 0)
        self.assertIsNone(result.error)
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output_tokens, 7)
        self.assertEqual(result.cache_read_tokens, 0)
        self.assertIsInstance(result.session_id, str)
        self.assertTrue(result.session_id)
        self.assertGreaterEqual(result.wall_time_seconds, 0.0)
        self.assertGreaterEqual(result.cost_usd, 0.0)

    async def test_run_completed_openai_path(self):
        agent = Agent(api_base="https://example.test/v1", api_key="test-key", is_sub_agent=True)

        async def _oai_stream(self):
            self._emit_text("\n")
            self._emit_text("hello")
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "cached_tokens": 0},
            }

        with patch.object(Agent, "_call_openai_stream", new=_oai_stream):
            result = await agent.run("hi")
        await agent.close()

        self.assertEqual(result.stop_reason, "completed")
        self.assertIn("hello", result.final_text)
        self.assertEqual(result.input_tokens, 8)
        self.assertEqual(result.output_tokens, 4)

    async def test_run_stop_reason_max_turns(self):
        agent = Agent(api_key="test-key", is_sub_agent=True, max_turns=1)
        responses = [_anthropic_response([_tool_block()])]
        with patch.object(Agent, "_call_anthropic_stream", new=_anthropic_stream(responses)):
            result = await agent.run("do something")
        await agent.close()

        self.assertEqual(result.stop_reason, "max_turns")
        self.assertEqual(result.turns, 1)

    async def test_run_model_error_captured(self):
        agent = Agent(api_key="test-key", is_sub_agent=True)

        async def _boom(self, on_tool_block_complete=None):
            raise RuntimeError("boom")

        with patch.object(Agent, "_call_anthropic_stream", new=_boom):
            result = await agent.run("hi")
        await agent.close()

        self.assertEqual(result.stop_reason, "model_error")
        self.assertIn("boom", result.error)
        self.assertEqual(result.final_text, "")

    async def test_run_timeout(self):
        agent = Agent(api_key="test-key", is_sub_agent=True)

        async def _hang(self, on_tool_block_complete=None):
            await asyncio.sleep(30)

        with patch.object(Agent, "_call_anthropic_stream", new=_hang):
            result = await agent.run("hi", timeout=0.1)
        await agent.close()

        self.assertEqual(result.stop_reason, "timeout")
        self.assertIsNotNone(result.error)

    async def test_run_timeout_covers_initial_mcp_discovery(self):
        agent = Agent(api_key="test-key")

        async def _slow_discovery():
            await asyncio.sleep(0.2)
            return []

        agent._mcp_manager.discover_tools = _slow_discovery
        responses = [_anthropic_response([_text_block("done")])]
        with patch.object(Agent, "_call_anthropic_stream", new=_anthropic_stream(responses)):
            result = await agent.run("hi", timeout=0.01)
        await agent.close()

        self.assertEqual(result.stop_reason, "timeout")
        self.assertLess(result.wall_time_seconds, 0.2)

    async def test_run_timeout_cancels_early_tool_tasks(self):
        agent = Agent(api_key="test-key", is_sub_agent=True)
        tool_started = asyncio.Event()
        tool_finished = asyncio.Event()

        async def _slow_tool(self, name, inp, tool_call_id=""):
            tool_started.set()
            try:
                await asyncio.sleep(30)
            finally:
                tool_finished.set()

        async def _stream(self, on_tool_block_complete=None):
            on_tool_block_complete({
                "type": "tool_use",
                "id": "t1",
                "name": "read_file",
                "input": {"file_path": "README.md"},
            })
            await tool_started.wait()
            await asyncio.sleep(30)

        with (
            patch.object(Agent, "_execute_tool_call", new=_slow_tool),
            patch.object(Agent, "_call_anthropic_stream", new=_stream),
        ):
            result = await agent.run("hi", timeout=0.05)
        await agent.close()

        self.assertEqual(result.stop_reason, "timeout")
        self.assertTrue(tool_finished.is_set())
        self.assertFalse(agent._early_tool_tasks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
