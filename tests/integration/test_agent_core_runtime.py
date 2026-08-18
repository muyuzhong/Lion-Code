"""Agent Core Runtime 单路径集成测试。

通过 patch ``lion_code.agent.create_provider`` 注入脚本化 ``FakeProvider``，
验证 ``chat`` 始终走 LionAgentRuntime，并覆盖工具闭环、动态 system、
动态工具、取消后继续会话和 Provider 热切换。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.fakes import FakeProvider

from lion_code.agent import Agent
from lion_code.context import SUMMARY_SYSTEM_PROMPT
from lion_code.core import (
    AssistantMessage,
    CompactionCompletedEvent,
    CompactionStartedEvent,
    TextContent,
    ToolCall,
    TurnEndEvent,
    Usage,
)
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent
from lion_code.provider_manager import ProviderManager
from lion_code.providers import RuntimeModelLimits
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult
from lion_code.usage import UsageSnapshot

_PLAN_REHOME = (
    "PR3 Kernel 不含 Plan：clear-and-execute 上下文清空 + 自动 continue 的增强"
    "依赖 Kernel 对 Plan 的特判，已随 Runtime 移除；待 Capability re-home PR 恢复"
)


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


def _tooluse_event(
    call_id: str = "c1", usage: Usage | None = None
) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[ToolCall(id=call_id, name="echo", arguments={"msg": "hi"})],
            stop_reason="toolUse",
            usage=usage or Usage(),
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


def _error_event(message: str = "provider failed") -> AssistantErrorEvent:
    return AssistantErrorEvent(
        reason="error",
        error=AssistantMessage(
            model="fake",
            content=[],
            stop_reason="error",
            error_message=message,
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
        self._temp_dir = tempfile.TemporaryDirectory()
        self._session_repository = SessionRepository(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def _make_agent(
        self,
        events: list,
        registry: ToolRegistry,
        **agent_kwargs,
    ) -> tuple[Agent, FakeProvider]:
        fake = FakeProvider(events)
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry,
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
                **agent_kwargs,
            )
        return agent, fake

    async def test_chat_always_uses_core_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        fake = FakeProvider([_stop_event("done")])
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry,
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )

        await agent.chat("hello")

        self.assertFalse(hasattr(Agent, "_chat_openai"))
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(agent.core_runtime.messages[-1].text, "done")

    async def test_core_runtime_updates_completed_outcome(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_stop_event("done")], registry)

        self.assertIsNotNone(agent._core_runtime)

        await agent.chat("hello")

        self.assertEqual(agent._core_runtime.messages[-1].text, "done")
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(agent._last_stop_reason, "completed")

    async def test_core_runtime_applies_provider_discovered_model_limits(self) -> None:
        fake = _LimitsFakeProvider(
            [_stop_event("done")],
            RuntimeModelLimits(context_window=128_000, max_output_tokens=8_000),
        )
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )

        await agent.chat("hello")

        self.assertEqual(agent.effective_window, 120_000)
        self.assertEqual(fake.discovered_models, [agent.model])

    async def test_abort_during_core_setup_stops_before_provider(self) -> None:
        setup_started = asyncio.Event()
        release_setup = asyncio.Event()

        async def resolve_limits(_provider, _model):
            setup_started.set()
            await release_setup.wait()
            return RuntimeModelLimits(
                context_window=128_000,
                max_output_tokens=8_000,
            )

        resolver = AsyncMock()
        resolver.resolve.side_effect = resolve_limits
        agent, fake = self._make_agent(
            [_stop_event("must not run")],
            ToolRegistry(),
            model_limits_resolver=resolver,
        )

        chat_task = asyncio.create_task(agent.chat("hello"))
        await setup_started.wait()
        agent.abort()
        release_setup.set()
        await chat_task

        self.assertEqual(fake.call_count, 0)
        self.assertEqual(agent._last_stop_reason, "aborted")
        self.assertTrue(agent.is_aborted)
        self.assertEqual(agent._core_runtime.messages, ())

    async def test_core_run_reports_provider_error(self) -> None:
        agent, _fake = self._make_agent(
            [_error_event("upstream failed")], ToolRegistry()
        )

        result = await agent.run("hello")

        self.assertEqual(result.stop_reason, "model_error")
        self.assertEqual(result.error, "upstream failed")
        self.assertEqual(result.turns, 0)
        self.assertEqual(agent._last_stop_reason, "model_error")

    async def test_tool_loop_through_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent(
            [_tooluse_event(), _stop_event("done")], registry
        )

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

    async def test_core_budget_keeps_max_turns_across_prompts(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent(
            [
                _tooluse_event("c1"),
                _stop_event("first done"),
                _tooluse_event("c2"),
            ],
            registry,
            max_turns=2,
        )

        await agent.chat("first")
        await agent.chat("second")

        self.assertEqual(fake.call_count, 3)
        self.assertEqual(agent.get_token_usage().turns, 2)
        self.assertEqual(agent._last_stop_reason, "max_turns")
        self.assertTrue(agent._core_runtime.messages[-1].is_error)
        self.assertIn("Turn limit reached", agent._core_runtime.messages[-1].text)

    async def test_core_budget_stops_before_tool_when_cost_limit_reached(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent(
            [_tooluse_event(usage=Usage(input=1_000))],
            registry,
            max_cost_usd=0.000_001,
        )

        await agent.chat("expensive")

        self.assertEqual(fake.call_count, 1)
        self.assertEqual(agent._last_stop_reason, "max_cost")
        self.assertTrue(agent._core_runtime.messages[-1].is_error)
        self.assertIn("Cost limit reached", agent._core_runtime.messages[-1].text)

    async def test_provider_gets_projection_while_harness_and_session_stay_full(
        self,
    ) -> None:
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
        self.assertTrue(
            all(
                message.text.startswith("durable-result-")
                for message in durable_results
            )
        )

        state = await self._session_repository.load(agent.session_id)
        session_results = [
            message for message in state.messages if message.role == "toolResult"
        ]
        self.assertEqual(
            [message.text for message in session_results],
            [message.text for message in durable_results],
        )

    async def test_automatic_compaction_persists_summary_and_keeps_recent_turn(
        self,
    ) -> None:
        registry = ToolRegistry()
        agent, fake = self._make_agent(
            [
                _stop_event("first answer", Usage(total_tokens=100)),
                _stop_event(
                    "second answer", Usage(input=160_000, total_tokens=160_000)
                ),
                _stop_event("condensed context"),
                _stop_event("third answer"),
            ],
            registry,
        )
        events = []
        agent.subscribe(events.append)

        await agent.chat("first question")
        await agent.chat("second question")
        await agent.chat("third question")

        self.assertEqual(fake.received_systems[2], SUMMARY_SYSTEM_PROMPT)
        self.assertEqual(fake.received_tools[2], [])
        self.assertEqual(
            [message.text for message in fake.received_messages[2][:-1]],
            ["first question", "first answer"],
        )
        projected = [message.text for message in fake.received_messages[3]]
        self.assertEqual(
            projected[:3],
            [
                "Previous conversation summary:\ncondensed context",
                "second question",
                "second answer",
            ],
        )
        self.assertEqual(projected[3], "third question")

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
            entry.message.text for entry in state.entries if entry.type == "message"
        ]
        self.assertIn("first question", raw_message_texts)
        self.assertIn("first answer", raw_message_texts)
        self.assertEqual(agent._core_runtime.messages, state.messages)
        usage = agent.get_token_usage()
        self.assertEqual(usage.last_prompt_tokens, 0)
        self.assertEqual(usage.input_tokens, 160_000)
        self.assertEqual(usage.responses, 3)
        self.assertFalse(agent._core_compaction_required)
        self.assertEqual(
            [
                event.reason
                for event in events
                if isinstance(event, CompactionStartedEvent)
            ],
            ["threshold"],
        )
        self.assertEqual(
            [
                (event.reason, event.aborted)
                for event in events
                if isinstance(event, CompactionCompletedEvent)
            ],
            [("threshold", False)],
        )

        restored, _ = self._make_agent([], registry)
        self.assertTrue(await restored.restore_core_session(agent.session_id))
        self.assertEqual(
            [message.text for message in restored._core_runtime.messages],
            [message.text for message in state.messages],
        )

    async def test_dynamic_system_prompt_refetched_per_turn(self) -> None:
        # 模拟 Plan 模式切换：运行中替换 Composer 动态尾部，下一轮请求读取新值。
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent(
            [_tooluse_event(), _stop_event("done")], registry
        )
        agent._prompt_composer.set_dynamic_context("initial")
        stable_base = agent._prompt_composer.stable_base_prompt

        mutated = {"done": False}

        async def mutate_after_first_turn(event) -> None:
            if not mutated["done"] and isinstance(event, TurnEndEvent):
                agent._prompt_composer.set_dynamic_context("plan-prompt")
                mutated["done"] = True

        agent._core_runtime.subscribe(mutate_after_first_turn)
        await agent.chat("hello")

        self.assertEqual(
            fake.received_systems,
            [f"{stable_base}\n\ninitial", f"{stable_base}\n\nplan-prompt"],
        )

    async def test_dynamic_tools_refetched_per_turn(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent(
            [_tooluse_event(), _stop_event("done")], registry
        )

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
        agent, fake = self._make_agent(
            [_tooluse_event(), _stop_event("done")], registry
        )

        cancelled = {"done": False}

        async def cancel_after_first_turn(event) -> None:
            if not cancelled["done"] and isinstance(event, TurnEndEvent):
                agent.core_runtime.cancel()
                cancelled["done"] = True

        agent._core_runtime.subscribe(cancel_after_first_turn)
        await agent.chat("hello")

        # 第一轮工具已执行，第二轮被取消，最终消息为 aborted。
        self.assertEqual(agent._core_runtime.messages[-1].stop_reason, "aborted")
        self.assertTrue(agent.is_aborted)
        self.assertEqual(agent._last_stop_reason, "aborted")

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
        session_path = self._session_repository.storage_for(session_id).path

        second, fake = self._make_agent([_stop_event("second answer")], registry)
        session_view = second.tool_context.session
        second._usage.record_child_usage(9, 8)
        second._usage.record_turn()
        self.assertTrue(await second.restore_core_session(session_id))
        self.assertEqual(second.get_token_usage(), UsageSnapshot())
        await second.chat("second question")

        self.assertEqual(second.session_id, session_id)
        self.assertIs(session_view, second.session_state)
        self.assertEqual(session_view.id, session_id)
        self.assertEqual(
            list(self._session_repository.session_dir.glob("*.jsonl")),
            [session_path],
        )
        self.assertEqual(list(self._session_repository.session_dir.glob("*.json")), [])
        projected = [message.text for message in fake.received_messages[0]]
        self.assertEqual(projected[:2], ["first question", "first answer"])
        self.assertEqual(projected[2], "second question")
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
        session_view = agent.tool_context.session
        usage = agent._usage
        usage_observer = agent._runtime_coordinator._usage_observer
        previous_path = self._session_repository.storage_for(previous_session_id).path
        agent._core_runtime.harness.follow_up("queued")
        for _ in range(3):
            agent._usage.record_turn()

        await agent.clear_history()

        self.assertNotEqual(agent.session_id, previous_session_id)
        self.assertIs(session_view, agent.session_state)
        self.assertEqual(session_view.id, agent.session_id)
        self.assertTrue(previous_path.exists())
        self.assertTrue(
            self._session_repository.storage_for(agent.session_id).path.exists()
        )
        self.assertEqual(agent._core_runtime.messages, ())
        self.assertEqual(agent.get_token_usage(), UsageSnapshot())
        self.assertIs(agent._usage, usage)
        self.assertIsNot(agent._runtime_coordinator._usage_observer, usage_observer)
        self.assertIs(agent._runtime_coordinator._usage_observer._ledger, usage)

    async def test_model_and_thinking_changes_are_restored(self) -> None:
        registry = ToolRegistry()
        agent, _ = self._make_agent([_stop_event()], registry)
        await agent.chat("hello")
        previous_provider = agent.core_runtime.provider
        agent.configure_api(model="claude-sonnet-4-6")
        self.assertIs(agent.core_runtime.provider, previous_provider)
        self.assertEqual(agent.set_thinking(True), "adaptive")
        await agent.close()

        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(state.model, "claude-sonnet-4-6")
        self.assertEqual(state.thinking_level, "adaptive")

        restored, _ = self._make_agent([], registry)
        self.assertTrue(await restored.restore_core_session(agent.session_id))
        self.assertEqual(restored.model, "claude-sonnet-4-6")
        # Core 路径恢复采用 Tau 档位;旧 SDK 词汇 "adaptive" 被 coerce 为 "medium"。
        self.assertEqual(restored.thinking_level, "medium")

    async def test_legacy_json_is_migrated_without_deleting_source(self) -> None:
        session_id = "legacy01"
        legacy_path = self._session_repository.session_dir / f"{session_id}.json"
        legacy_source = json.dumps(
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
        )
        legacy_path.write_text(legacy_source, encoding="utf-8")
        legacy_file_state = (
            legacy_path.name,
            legacy_path.read_bytes(),
            legacy_path.stat().st_mtime_ns,
        )
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_stop_event("new answer")], registry)

        discovered = await agent.list_sessions()
        self.assertEqual(
            [(item["id"], item["format"]) for item in discovered],
            [(session_id, "json")],
        )
        self.assertEqual(await agent.latest_session_id(), session_id)
        self.assertTrue(await agent.restore_latest_session())
        jsonl_path = self._session_repository.storage_for(session_id).path
        self.assertEqual(
            (
                legacy_path.name,
                legacy_path.read_bytes(),
                legacy_path.stat().st_mtime_ns,
            ),
            legacy_file_state,
        )
        self.assertTrue(jsonl_path.exists())
        await agent.chat("continue")

        self.assertEqual(
            (
                legacy_path.name,
                legacy_path.read_bytes(),
                legacy_path.stat().st_mtime_ns,
            ),
            legacy_file_state,
        )
        self.assertEqual(
            list(self._session_repository.session_dir.glob("*.json")),
            [legacy_path],
        )
        self.assertEqual(
            list(self._session_repository.session_dir.glob("*.jsonl")),
            [jsonl_path],
        )
        self.assertEqual(
            [message.role for message in fake.received_messages[0]],
            ["user", "assistant", "toolResult", "assistant", "user"],
        )
        state = await self._session_repository.load(session_id)
        self.assertEqual(
            [message.text for message in state.messages],
            [
                "old question",
                "",
                "legacy result",
                "old answer",
                "continue",
                "new answer",
            ],
        )
        sessions = [
            item for item in await agent.list_sessions() if item["id"] == session_id
        ]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["format"], "jsonl")

    @unittest.skip(_PLAN_REHOME)
    async def test_plan_clear_and_execute_compacts_without_deleting_history(
        self,
    ) -> None:
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
                        usage=Usage(input=11, output=2, total_tokens=13),
                    ),
                ),
                _stop_event(
                    "implemented",
                    Usage(input=7, output=3, total_tokens=10),
                ),
            ]
        )
        plan_path = Path(self._temp_dir.name) / "approved-plan.md"
        plan_path.write_text("1. change code\n2. run tests", encoding="utf-8")
        with (
            patch("lion_code.agent.create_provider", return_value=fake),
            patch(
                "lion_code.plan_runtime.PlanRuntime._generate_file_path",
                return_value=plan_path,
            ),
        ):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )
        agent.toggle_plan_mode()
        permission = agent.tool_context.permission
        agent.tool_registry.activate("exit_plan_mode")

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
        self.assertIs(agent.tool_context.permission, permission)
        self.assertEqual(permission.mode, "default")
        self.assertEqual(agent.permission_mode, "default")
        usage = agent.get_token_usage()
        self.assertEqual((usage.input_tokens, usage.output_tokens), (18, 5))
        self.assertEqual(usage.responses, 2)
        self.assertEqual(usage.last_prompt_tokens, 10)

        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(
            [message.role for message in state.messages],
            ["user", "assistant"],
        )
        self.assertEqual(len(state.compaction_entries), 1)
        self.assertEqual(len(state.compaction_entries[0].replaces_entry_ids), 3)
        self.assertGreater(len(state.entries), len(state.messages))

    async def test_plan_clear_and_execute_degrades_to_execute(self) -> None:
        """clear-and-execute 不再清空上下文：同一上下文继续；权限模式不受 Plan 影响。"""

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
                        usage=Usage(input=11, output=2, total_tokens=13),
                    ),
                ),
                _stop_event(
                    "implemented",
                    Usage(input=7, output=3, total_tokens=10),
                ),
            ]
        )
        plan_path = Path(self._temp_dir.name) / "approved-plan.md"
        plan_path.write_text("1. change code\n2. run tests", encoding="utf-8")
        with (
            patch("lion_code.agent.create_provider", return_value=fake),
            patch(
                "lion_code.plan_runtime.PlanRuntime._generate_file_path",
                return_value=plan_path,
            ),
        ):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )
        agent.toggle_plan_mode()
        permission = agent.tool_context.permission
        agent.tool_registry.activate("exit_plan_mode")

        async def approve(_plan: str) -> dict:
            return {"choice": "clear-and-execute"}

        agent.set_plan_approval_fn(approve)
        await agent.chat("prepare the change")

        self.assertEqual(fake.call_count, 2)
        # 未清空上下文：第二次调用仍是完整历史，而不是摘要单条。
        self.assertEqual(
            [message.role for message in fake.received_messages[1]],
            ["user", "assistant", "toolResult"],
        )
        self.assertEqual(agent._core_runtime.messages[-1].text, "implemented")
        self.assertIs(agent.tool_context.permission, permission)
        # PR4：审批通过不再把权限切换到 acceptEdits。
        self.assertEqual(permission.mode, "default")
        state = await self._session_repository.load(agent.session_id)
        self.assertEqual(len(state.compaction_entries), 0)

    @unittest.skip(_PLAN_REHOME)
    async def test_plan_context_reset_failure_keeps_pending_command(self) -> None:
        fake = FakeProvider([])
        plan_path = Path(self._temp_dir.name) / "failing-reset-plan.md"
        plan_path.write_text("keep this plan", encoding="utf-8")
        with (
            patch("lion_code.agent.create_provider", return_value=fake),
            patch(
                "lion_code.plan_runtime.PlanRuntime._generate_file_path",
                return_value=plan_path,
            ),
        ):
            agent = Agent(
                permission_mode="plan",
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )

        async def approve(_plan: str) -> dict:
            return {"choice": "clear-and-execute"}

        agent.set_plan_approval_fn(approve)
        outcome = await agent.tool_runtime.execute(
            tool_call_id="exit-plan",
            name="exit_plan_mode",
            arguments={},
        )
        self.assertTrue(outcome.terminate)
        pending = agent.plan.pending_context_reset
        self.assertIsNotNone(pending)
        await agent._ensure_core_session_ready()

        with patch.object(
            agent._core_runtime,
            "reset_active_context",
            AsyncMock(side_effect=RuntimeError("reset failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "reset failed"):
                await agent._runtime_coordinator.apply_plan_context_reset()

        self.assertEqual(agent.plan.pending_context_reset, pending)
        await agent.close()

    async def test_configure_api_replaces_provider_in_existing_runtime(self) -> None:
        """换 key/base 原位替换 Provider，并保留 Harness 与 canonical history。"""
        agent, old_fake = self._make_agent([_stop_event("done")], ToolRegistry())
        self.assertIsInstance(agent._provider_manager, ProviderManager)
        await agent.chat("hello")
        old_runtime = agent._core_runtime
        old_compactor = agent._context_compactor

        new_fake = FakeProvider([_stop_event("again")])
        with patch(
            "lion_code.agent.create_provider", return_value=new_fake
        ) as mock_create:
            agent.configure_api(api_key="new-key", api_base="https://new.test/v1")

        mock_create.assert_called_once_with(
            api_key="new-key", api_base="https://new.test/v1", thinking_level="off"
        )
        self.assertIs(agent._core_runtime, old_runtime)
        self.assertEqual(
            [m.role for m in agent._core_runtime.messages], ["user", "assistant"]
        )
        self.assertIsNot(agent._context_compactor, old_compactor)
        self.assertIs(agent._context_compactor._provider, new_fake)
        self.assertIsNone(agent._resolved_model_limits_for)

        # 新 Provider 接管后续请求。
        await agent.chat("second")
        self.assertTrue(old_fake.closed)
        self.assertFalse(new_fake.closed)
        self.assertEqual(new_fake.call_count, 1)
        self.assertEqual(agent._core_runtime.messages[-1].text, "again")
        await agent.close()
        self.assertTrue(new_fake.closed)

    async def test_configure_api_failure_keeps_complete_state(self) -> None:
        agent, provider = self._make_agent([], ToolRegistry())
        runtime = agent.core_runtime
        compactor = agent._context_compactor
        config = agent.get_api_config()

        with (
            patch(
                "lion_code.agent.create_provider",
                side_effect=RuntimeError("bad provider config"),
            ),
            self.assertRaisesRegex(RuntimeError, "bad provider config"),
        ):
            agent.configure_api(
                model="new-model",
                api_key="new-key",
                api_base="https://new.test/v1",
            )

        self.assertIs(agent.core_runtime, runtime)
        self.assertIs(agent.core_runtime.provider, provider)
        self.assertIs(agent._context_compactor, compactor)
        self.assertEqual(agent.get_api_config(), config)
        self.assertFalse(provider.closed)

    async def test_configure_api_rejects_busy_runtime_without_changes(self) -> None:
        agent, provider = self._make_agent([], ToolRegistry())
        config = agent.get_api_config()
        agent.core_runtime.harness._running = True
        try:
            with (
                patch("lion_code.agent.create_provider") as create,
                self.assertRaisesRegex(RuntimeError, "运行中"),
            ):
                agent.configure_api(api_key="new-key")
        finally:
            agent.core_runtime.harness._running = False

        create.assert_not_called()
        self.assertIs(agent.core_runtime.provider, provider)
        self.assertEqual(agent.get_api_config(), config)

    async def test_configure_api_keeps_usage_for_cost_budget(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, _old_fake = self._make_agent(
            [
                _tooluse_event("c1", usage=Usage(input=1_000)),
                _stop_event("first done"),
            ],
            registry,
            max_cost_usd=0.0045,
        )
        await agent.chat("first")

        new_fake = FakeProvider([_tooluse_event("c2", usage=Usage(input=1_000))])
        with patch("lion_code.agent.create_provider", return_value=new_fake):
            agent.configure_api(api_key="new-key")

        await agent.chat("second")

        self.assertEqual(agent.get_token_usage().input_tokens, 2_000)
        self.assertEqual(agent._last_stop_reason, "max_cost")
        self.assertEqual(new_fake.call_count, 1)
        self.assertTrue(agent._core_runtime.messages[-1].is_error)
        self.assertIn("Cost limit reached", agent._core_runtime.messages[-1].text)

    async def test_anthropic_backend_routes_to_core_runtime(self) -> None:
        """Anthropic 后端(无 api_base)同样走 Core Runtime,不再落 legacy。"""
        fake = FakeProvider([_stop_event("done")])
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_key="ak",
                tool_registry=ToolRegistry(),
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )

        self.assertFalse(agent.use_openai)
        self.assertIsNotNone(agent.core_runtime)

        await agent.chat("hello")

        self.assertFalse(hasattr(Agent, "_chat_anthropic"))
        self.assertEqual(agent._core_runtime.messages[-1].text, "done")
        self.assertEqual(fake.call_count, 1)

    async def test_cross_protocol_switch_keeps_messages(self) -> None:
        """OpenAI→Anthropic 切换重建 Provider,canonical 历史保留。"""
        agent, _fake = self._make_agent([_stop_event("done")], ToolRegistry())
        await agent.chat("hello")

        new_fake = FakeProvider([_stop_event("再见")])
        with patch(
            "lion_code.agent.create_provider", return_value=new_fake
        ) as mock_create:
            agent.configure_api(use_openai=False, api_key="ak")

        self.assertIn("anthropic_base_url", mock_create.call_args.kwargs)
        self.assertEqual(
            [m.role for m in agent._core_runtime.messages], ["user", "assistant"]
        )

        await agent.chat("second")
        self.assertEqual(new_fake.call_count, 1)
        self.assertEqual(agent._core_runtime.messages[-1].text, "再见")

    async def test_sub_agent_runs_on_core_runtime(self) -> None:
        """子 Agent 也走 Core:凭证随 fork 传递,文本经 canonical 兜底捕获。"""
        parent_fake = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[
                            ToolCall(
                                id="a1",
                                name="agent",
                                arguments={
                                    "agent_type": "general",
                                    "description": "demo",
                                    "prompt": "do the thing",
                                },
                            )
                        ],
                        stop_reason="toolUse",
                    ),
                ),
                _stop_event("parent done"),
            ]
        )
        sub_fake = FakeProvider([_stop_event("sub says hi")])
        with (
            patch("lion_code.agent.create_provider", return_value=parent_fake),
            patch(
                "lion_code.composition.agent_builder.create_provider",
                return_value=sub_fake,
            ) as create,
            patch("lion_code.agent.TerminalRenderer") as terminal_renderer,
        ):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=False,
            )
            await agent.chat("hello")

        self.assertEqual(sub_fake.call_count, 1)
        terminal_renderer.assert_not_called()
        self.assertEqual(
            create.call_args.kwargs,
            {
                "api_key": "test-key",
                "api_base": "https://example.test/v1",
                "thinking_level": "off",
            },
        )
        self.assertEqual(
            [m.role for m in agent._core_runtime.messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertIn("sub says hi", agent._core_runtime.messages[2].text)
        # 子 Agent 不落盘会话:仓库里只有父会话。
        sessions = await self._session_repository.list_sessions()
        self.assertEqual(len(sessions), 1)

    async def test_configure_api_model_only_keeps_core_provider(self) -> None:
        """只改模型不重建 Provider,经 set_model 直接生效。"""
        agent, fake = self._make_agent([_stop_event("done")], ToolRegistry())
        old_runtime = agent._core_runtime

        agent.configure_api(model="new-model")

        self.assertIs(agent._core_runtime, old_runtime)
        self.assertEqual(agent._core_runtime.harness.config.model, "new-model")
        await agent.chat("hello")
        self.assertEqual(fake.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
