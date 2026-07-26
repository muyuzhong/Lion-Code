"""Agent 入口灰度切换集成测试：证明真实 ``Agent.chat`` 已切到新 Core Runtime。

通过 patch ``lion_code.agent.create_provider`` 注入脚本化 ``FakeProvider``，
验证 ``LION_CORE_RUNTIME=1`` 时 ``chat`` 走 LionAgentRuntime 而非旧
``_chat_openai``，并覆盖工具闭环、动态 system、动态工具、取消后继续会话。
``LION_CORE_RUNTIME=0`` 时仍走旧路径。
"""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.context import SUMMARY_SYSTEM_PROMPT
from lion_code.core import AssistantMessage, TextContent, ToolCall, TurnEndEvent, Usage
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.providers import RuntimeModelLimits
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult
from lion_code.ui import set_sink

from core.fakes import FakeProvider


class _LimitsFakeProvider(FakeProvider):
    def __init__(self, events: list, limits: RuntimeModelLimits) -> None:
        super().__init__(events)
        self.limits = limits
        self.discovered_models: list[str] = []

    async def discover_model_limits(self, model: str) -> RuntimeModelLimits | None:
        self.discovered_models.append(model)
        return self.limits


def _echo_lion_tool() -> LionTool:
    async def execute(_ctx, _id, arguments, _on_update):
        return ToolResult(content=f"echo:{arguments.get('msg', '')}")

    return LionTool(
        name="echo",
        label="Echo",
        description="echo the msg argument",
        parameters={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True, concurrency_safe=True),
        execution_mode="parallel",
    )


def _named_lion_tool(name: str) -> LionTool:
    async def execute(_ctx, _id, _args, _on_update):
        return ToolResult(content=f"{name}-result")

    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object"},
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True, concurrency_safe=True),
        execution_mode="parallel",
    )


def _snippable_lion_tool() -> LionTool:
    async def execute(_ctx, _id, arguments, _on_update):
        return ToolResult(content=f"durable-result-{arguments['index']}-" + "x" * 200)

    return LionTool(
        name="snippable",
        label="Snippable",
        description="return a rereadable result",
        parameters={
            "type": "object",
            "properties": {"index": {"type": "integer"}},
            "required": ["index"],
        },
        execute_fn=execute,
        capabilities=ToolCapabilities(
            read_only=True,
            concurrency_safe=True,
            result_policy="snippable",
        ),
        execution_mode="parallel",
    )


def _tooluse_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[ToolCall(id="c1", name="echo", arguments={"msg": "hi"})],
            stop_reason="toolUse",
        ),
    )


def _stop_event(text: str = "done", usage: Usage | None = None) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
            usage=usage or Usage(),
        ),
    )


def _many_tooluse_event(count: int, usage: Usage) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[
                ToolCall(
                    id=f"snip-{index}",
                    name="snippable",
                    arguments={"index": index},
                )
                for index in range(count)
            ],
            stop_reason="toolUse",
            usage=usage,
        ),
    )


class TestAgentCoreRuntime(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # 捕获所有 ui 输出，避免测试污染 stdout。
        self._collected: list[tuple[str, dict]] = []
        self._prev_sink = set_sink(lambda kind, data: self._collected.append((kind, data)))
        self._temp_dir = tempfile.TemporaryDirectory()
        self._session_repository = SessionRepository(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        set_sink(self._prev_sink)
        os.environ.pop("LION_CORE_RUNTIME", None)
        self._temp_dir.cleanup()

    def _make_agent(self, events: list, registry: ToolRegistry) -> tuple[Agent, FakeProvider]:
        fake = FakeProvider(events)
        os.environ["LION_CORE_RUNTIME"] = "1"
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry,
                custom_system_prompt="test",
                session_repository=self._session_repository,
            )
        # 跳过 MCP 发现，避免测试环境副作用。
        agent._mcp_initialized = True
        return agent, fake

    async def test_grayscale_off_uses_old_path(self) -> None:
        os.environ["LION_CORE_RUNTIME"] = "0"
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent = Agent(
            api_base="https://example.test/v1",
            api_key="test-key",
            tool_registry=registry,
            custom_system_prompt="test",
        )
        agent._mcp_initialized = True

        self.assertIsNone(agent._core_runtime)
        self.assertFalse(agent._use_core_runtime)

        with (
            patch.object(Agent, "_chat_openai", new_callable=AsyncMock) as mock_chat,
            patch.object(Agent, "_auto_save", lambda self: None),
        ):
            await agent.chat("hello")

        mock_chat.assert_called_once_with("hello")

    async def test_grayscale_on_routes_to_core_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_stop_event("done")], registry)

        self.assertIsNotNone(agent._core_runtime)

        with patch.object(Agent, "_chat_openai", new_callable=AsyncMock) as mock_chat:
            await agent.chat("hello")

        # 不再调用旧路径。
        mock_chat.assert_not_called()
        self.assertEqual(agent._core_runtime.messages[-1].text, "done")
        self.assertEqual(fake.call_count, 1)

    async def test_core_runtime_applies_provider_discovered_model_limits(self) -> None:
        fake = _LimitsFakeProvider(
            [_stop_event("done")],
            RuntimeModelLimits(context_window=128_000, max_output_tokens=8_000),
        )
        os.environ["LION_CORE_RUNTIME"] = "1"
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
            )
        agent._mcp_initialized = True

        await agent.chat("hello")

        self.assertEqual(agent.effective_window, 120_000)
        self.assertEqual(fake.discovered_models, [agent.model])

    async def test_tool_loop_through_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)

        await agent.chat("hello")

        messages = agent._core_runtime.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[-1].text, "done")
        self.assertEqual(fake.call_count, 2)
        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(
            [message.role for message in state.messages],
            ["user", "assistant", "toolResult", "assistant"],
        )

    async def test_provider_gets_projection_while_harness_and_session_stay_full(self) -> None:
        registry = ToolRegistry()
        registry.register(_snippable_lion_tool())
        agent, fake = self._make_agent(
            [
                _many_tooluse_event(5, Usage(input=140_000, total_tokens=140_000)),
                _stop_event("done"),
            ],
            registry,
        )

        await agent.chat("hello")

        projected_results = [
            message
            for message in fake.received_messages[1]
            if message.role == "toolResult"
        ]
        self.assertEqual(
            [message.text for message in projected_results[:2]],
            [agent._context_manager.policy.snip_placeholder] * 2,
        )
        durable_results = [
            message
            for message in agent._core_runtime.messages
            if message.role == "toolResult"
        ]
        self.assertTrue(all(message.text.startswith("durable-result-") for message in durable_results))

        state = await self._session_repository.load(agent.session_id)
        session_results = [
            message for message in state.messages if message.role == "toolResult"
        ]
        self.assertEqual(
            [message.text for message in session_results],
            [message.text for message in durable_results],
        )

    async def test_automatic_compaction_persists_summary_and_keeps_recent_turn(self) -> None:
        registry = ToolRegistry()
        agent, fake = self._make_agent(
            [
                _stop_event("first answer", Usage(total_tokens=100)),
                _stop_event("second answer", Usage(input=160_000, total_tokens=160_000)),
                _stop_event("condensed context"),
                _stop_event("third answer"),
            ],
            registry,
        )

        await agent.chat("first question")
        await agent.chat("second question")
        await agent.chat("third question")

        self.assertEqual(fake.received_systems[2], SUMMARY_SYSTEM_PROMPT)
        self.assertEqual(fake.received_tools[2], [])
        self.assertEqual(
            [message.text for message in fake.received_messages[2][:-1]],
            ["first question", "first answer"],
        )
        self.assertEqual(
            [message.text for message in fake.received_messages[3]],
            [
                "Previous conversation summary:\ncondensed context",
                "second question",
                "second answer",
                "third question",
            ],
        )

        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(len(state.compaction_entries), 1)
        self.assertEqual(len(state.compaction_entries[0].replaces_entry_ids), 2)
        self.assertEqual(
            [message.text for message in state.messages],
            [
                "Previous conversation summary:\ncondensed context",
                "second question",
                "second answer",
                "third question",
                "third answer",
            ],
        )
        raw_message_texts = [
            entry.message.text
            for entry in state.entries
            if entry.type == "message"
        ]
        self.assertIn("first question", raw_message_texts)
        self.assertIn("first answer", raw_message_texts)
        self.assertEqual(agent._core_runtime.messages, state.messages)
        self.assertEqual(agent.last_input_token_count, 0)
        self.assertFalse(agent._core_compaction_required)

        restored, _ = self._make_agent([], registry)
        self.assertTrue(await restored.restore_core_session(agent.session_id))
        self.assertEqual(
            [message.text for message in restored._core_runtime.messages],
            [message.text for message in state.messages],
        )

    async def test_dynamic_system_prompt_refetched_per_turn(self) -> None:
        # 模拟 Plan 模式切换：运行中改 _system_prompt，下一轮请求必须看到新值。
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)
        agent._system_prompt = "initial"

        mutated = {"done": False}

        async def mutate_after_first_turn(event) -> None:
            if not mutated["done"] and isinstance(event, TurnEndEvent):
                agent._system_prompt = "plan-prompt"
                mutated["done"] = True

        agent._core_runtime.subscribe(mutate_after_first_turn)
        await agent.chat("hello")

        self.assertEqual(fake.received_systems, ["initial", "plan-prompt"])

    async def test_dynamic_tools_refetched_per_turn(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)

        added = {"done": False}

        async def activate_after_first_turn(event) -> None:
            if not added["done"] and isinstance(event, TurnEndEvent):
                registry.register(_named_lion_tool("late"))
                added["done"] = True

        agent._core_runtime.subscribe(activate_after_first_turn)
        await agent.chat("hello")

        self.assertNotIn("late", fake.received_tools[0])
        self.assertIn("late", fake.received_tools[1])

    async def test_cancel_then_continue_without_incomplete_tool_call(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)

        cancelled = {"done": False}

        async def cancel_after_first_turn(event) -> None:
            if not cancelled["done"] and isinstance(event, TurnEndEvent):
                agent._core_runtime.cancel()
                cancelled["done"] = True

        agent._core_runtime.subscribe(cancel_after_first_turn)
        await agent.chat("hello")

        # 第一轮工具已执行，第二轮被取消，最终消息为 aborted。
        self.assertEqual(agent._core_runtime.messages[-1].stop_reason, "aborted")

        # 再次 chat：不遗留不完整工具调用，能正常收敛到最终文本。
        await agent.chat("again")
        self.assertEqual(agent._core_runtime.messages[-1].text, "done")
        # 第一轮 + 被取消的第二轮 + 续聊一轮，共 3 次 provider 调用。
        self.assertEqual(fake.call_count, 3)

    async def test_restore_continues_with_persisted_harness_messages(self) -> None:
        registry = ToolRegistry()
        first, _ = self._make_agent([_stop_event("first answer")], registry)
        await first.chat("first question")
        session_id = first.session_id

        second, fake = self._make_agent([_stop_event("second answer")], registry)
        self.assertTrue(await second.restore_core_session(session_id))
        await second.chat("second question")

        self.assertEqual(
            [message.text for message in fake.received_messages[0]],
            ["first question", "first answer", "second question"],
        )
        state = await self._session_repository.load(session_id)
        self.assertEqual(
            [message.text for message in state.messages],
            ["first question", "first answer", "second question", "second answer"],
        )

    async def test_clear_creates_new_session_and_preserves_old_jsonl(self) -> None:
        registry = ToolRegistry()
        agent, _ = self._make_agent([_stop_event()], registry)
        await agent.chat("hello")
        previous_session_id = agent.session_id
        previous_path = self._session_repository.storage_for(previous_session_id).path
        agent._core_runtime.harness.follow_up("queued")
        agent.current_turns = 3

        await agent.clear_history()

        self.assertNotEqual(agent.session_id, previous_session_id)
        self.assertTrue(previous_path.exists())
        self.assertTrue(self._session_repository.storage_for(agent.session_id).path.exists())
        self.assertEqual(agent._core_runtime.messages, ())
        self.assertEqual(agent._core_runtime.harness.pending_message_count, 0)
        self.assertEqual(agent.current_turns, 0)

    async def test_model_and_thinking_changes_are_restored(self) -> None:
        registry = ToolRegistry()
        agent, _ = self._make_agent([_stop_event()], registry)
        await agent.chat("hello")
        previous_client = agent._openai_client
        agent.configure_api(model="claude-sonnet-4-6")
        self.assertIs(agent._openai_client, previous_client)
        self.assertEqual(agent.set_thinking(True), "adaptive")
        await agent.close()

        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(state.model, "claude-sonnet-4-6")
        self.assertEqual(state.thinking_level, "adaptive")

        restored, _ = self._make_agent([], registry)
        self.assertTrue(await restored.restore_core_session(agent.session_id))
        self.assertEqual(restored.model, "claude-sonnet-4-6")
        self.assertEqual(restored._thinking_mode, "adaptive")

    async def test_legacy_json_is_migrated_without_deleting_source(self) -> None:
        session_id = "legacy01"
        legacy_path = self._session_repository.session_dir / f"{session_id}.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "id": session_id,
                        "model": "legacy-model",
                        "cwd": str(Path.cwd().resolve()),
                        "startTime": "2026-01-01T00:00:00Z",
                    },
                    "openaiMessages": [
                        {"role": "system", "content": "old system"},
                        {"role": "user", "content": "old question"},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "old-call",
                                    "type": "function",
                                    "function": {
                                        "name": "echo",
                                        "arguments": '{"msg":"legacy"}',
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "old-call",
                            "content": "legacy result",
                        },
                        {"role": "assistant", "content": "old answer"},
                    ],
                    "anthropicMessages": None,
                }
            ),
            encoding="utf-8",
        )
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_stop_event("new answer")], registry)

        self.assertTrue(await agent.restore_session_id(session_id))
        self.assertTrue(legacy_path.exists())
        self.assertTrue(self._session_repository.storage_for(session_id).path.exists())
        await agent.chat("continue")

        self.assertEqual(
            [message.role for message in fake.received_messages[0]],
            ["user", "assistant", "toolResult", "assistant", "user"],
        )
        sessions = [
            item for item in await agent.list_sessions() if item["id"] == session_id
        ]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["format"], "jsonl")

    async def test_plan_clear_and_execute_compacts_without_deleting_history(self) -> None:
        fake = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[
                            ToolCall(
                                id="exit-plan",
                                name="exit_plan_mode",
                                arguments={},
                            )
                        ],
                        stop_reason="toolUse",
                    ),
                ),
                _stop_event("implemented"),
            ]
        )
        os.environ["LION_CORE_RUNTIME"] = "1"
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                permission_mode="plan",
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
            )
        agent._mcp_initialized = True
        agent.tool_registry.activate("exit_plan_mode")
        plan_path = Path(self._temp_dir.name) / "approved-plan.md"
        plan_path.write_text("1. change code\n2. run tests", encoding="utf-8")
        agent._plan_file_path = str(plan_path)
        agent.tool_context.plan_file_path = str(plan_path)

        async def approve(_plan: str) -> dict:
            return {"choice": "clear-and-execute"}

        agent.set_plan_approval_fn(approve)
        await agent.chat("prepare the change")

        self.assertEqual(fake.call_count, 2)
        self.assertEqual(len(fake.received_messages[1]), 1)
        self.assertIn("Approved plan", fake.received_messages[1][0].text)
        self.assertEqual(
            [message.role for message in agent._core_runtime.messages],
            ["user", "assistant"],
        )
        self.assertEqual(agent._core_runtime.messages[-1].text, "implemented")
        self.assertEqual(agent.tool_context.permission_mode, "acceptEdits")

        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(
            [message.role for message in state.messages],
            ["user", "assistant"],
        )
        self.assertEqual(len(state.compaction_entries), 1)
        self.assertEqual(len(state.compaction_entries[0].replaces_entry_ids), 3)
        self.assertGreater(len(state.entries), len(state.messages))


if __name__ == "__main__":
    unittest.main(verbosity=2)
