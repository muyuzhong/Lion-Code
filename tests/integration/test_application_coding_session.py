"""LionCodingSession 阶段 1 验收测试。

用脚本化 FakeProvider 驱动真实 ``Agent``(Core Runtime 路径),验证:
文本/工具闭环的事件流、AgentEnd→SessionAgentEnd→Settled 次序、
运行中入队(steer)、取消、messages 与 JSONL Session 一致。
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_agent import build_full_agent_harness

from lion_code.adapters.coding_session_backend import CodingSessionBackendAdapter
from lion_code.application import (
    AgentSettledEvent,
    AutoRetryEndEvent,
    AutoRetryStartEvent,
    CompactionEndEvent,
    CompactionStartEvent,
    LionCodingSession,
    QueueUpdateEvent,
    SessionAgentEndEvent,
)
from lion_code.context import (
    SUMMARY_HEADINGS,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from lion_code.core import AssistantMessage, TextContent, ToolCall
from lion_code.core.events import (
    AgentEndEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from lion_code.core.events import (
    CompactionCompletedEvent as KernelCompactionCompletedEvent,
)
from lion_code.core.events import (
    CompactionStartedEvent as KernelCompactionStartedEvent,
)
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


def _structured_summary(content: str) -> str:
    return "\n\n".join(f"{heading}\n{content}" for heading in SUMMARY_HEADINGS)


def _echo_lion_tool(gate: asyncio.Event | None = None) -> LionTool:
    """echo 工具;传入 gate 时在放行前挂起,用于制造真实的运行中状态。"""

    async def execute(_ctx, _id, arguments, _on_update):
        if gate is not None:
            await gate.wait()
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


def _tooluse_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[ToolCall(id="c1", name="echo", arguments={"msg": "hi"})],
            stop_reason="toolUse",
        ),
    )


def _stop_event(text: str = "done") -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
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


class TestLionCodingSession(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._session_repository = SessionRepository(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def _make_session(
        self,
        events: list,
        registry: ToolRegistry | None = None,
        *,
        terminal_output: bool = False,
    ):
        from pathlib import Path as _Path

        from core.fakes import FakeProvider

        fake = FakeProvider(events)
        with patch("full_agent.create_provider", return_value=fake):
            harness = build_full_agent_harness(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry or ToolRegistry(),
                custom_system_prompt="test",
                session_repository=self._session_repository,
                terminal_output=terminal_output,
            )
        composition = harness.composition
        agent = CodingSessionBackendAdapter(
            agent=harness.agent,
            plan=composition.capabilities.plan,
            confirmation=composition.interaction.confirmation,
            notices=composition.interaction.notices,
            status_sink=composition.interaction.status_sink,
            terminal_output_sink=composition.runtime.agent.set_terminal_output,
            session_renamer=composition.runtime.session.rename_session,
            session_repository=composition.runtime.session.repository,
            cwd=_Path(composition.tooling.context.cwd),
        )
        return LionCodingSession(agent), agent, harness, fake

    # ─── 构造约束 ────────────────────────────────────────────

    async def test_uses_injected_backend(self) -> None:
        session, agent, _harness, _fake = self._make_session([])
        self.assertIs(session._backend, agent)
        self.assertIsNone(_harness.composition.runtime.agent._terminal_renderer)

    async def test_rename_active_session_persists_label(self) -> None:
        session, _agent, harness, _fake = self._make_session([_stop_event("ready")])
        [event async for event in session.prompt("start")]

        session_id = harness.agent.session_id
        self.assertTrue(await session.rename_session(session_id, "需求文档"))
        state = await self._session_repository.load(session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.label, "需求文档")
        await session.aclose()

    async def test_structured_session_only_unsubscribes_terminal_renderer(self) -> None:
        with patch("full_agent.TerminalRenderer") as renderer_factory:
            session, agent, harness, _fake = self._make_session(
                [_stop_event("before"), _stop_event("after")],
                terminal_output=True,
            )
            await agent.chat("first")

            recorder = harness.composition.runtime.agent.session.recorder
            usage = harness.composition.runtime.usage
            usage_observer = harness.composition.runtime.agent._usage_observer
            self.assertIsNotNone(recorder)
            self.assertTrue(recorder.initialized)
            self.assertEqual(usage.snapshot().responses, 1)

            session = LionCodingSession(agent)
            self.assertIs(harness.composition.runtime.agent.session.recorder, recorder)
            self.assertIs(harness.composition.runtime.usage, usage)
            self.assertIs(
                harness.composition.runtime.agent._usage_observer,
                usage_observer,
            )
            self.assertIsNone(harness.composition.runtime.agent._terminal_renderer)
            renderer_factory.assert_called_once_with()

            [event async for event in session.prompt("second")]

        entries = await self._session_repository.storage_for(
            harness.agent.session_id
        ).read_all()
        self.assertEqual(sum(entry.type == "session_info" for entry in entries), 1)
        self.assertEqual(sum(entry.type == "message" for entry in entries), 4)
        self.assertEqual(usage.snapshot().responses, 2)
        await session.aclose()

    async def test_unconfigured_agent_reports_error_through_session_notice(
        self,
    ) -> None:
        from core.fakes import FakeProvider

        fake = FakeProvider([])
        with (
            patch.dict(
                "os.environ",
                {"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": ""},
            ),
            patch("full_agent.create_provider", return_value=fake),
        ):
            harness = build_full_agent_harness(
                api_key=None,
                custom_system_prompt="test",
                session_repository=self._session_repository,
            )
            composition = harness.composition
            agent = CodingSessionBackendAdapter(
                agent=harness.agent,
                plan=composition.capabilities.plan,
                confirmation=composition.interaction.confirmation,
                notices=composition.interaction.notices,
                status_sink=composition.interaction.status_sink,
                terminal_output_sink=composition.runtime.agent.set_terminal_output,
                session_renamer=composition.runtime.session.rename_session,
                session_repository=composition.runtime.session.repository,
                cwd=Path(composition.tooling.context.cwd),
            )
        session = LionCodingSession(agent)
        notices: list[tuple[str, str]] = []
        session.set_notice_fn(lambda message, role: notices.append((message, role)))

        events = [event async for event in session.prompt("hi")]

        self.assertTrue(
            any(
                role == "error" and "API 未配置" in message for message, role in notices
            )
        )
        # 未配置时不静默：事件流必须包含一条可见的 error assistant 消息，
        # 使桌面/REST 前端不依赖 notice 也能呈现明确失败（R2 回归）。
        err_events = [
            event
            for event in events
            if isinstance(event, (MessageStartEvent, MessageEndEvent))
            and event.message.role == "assistant"
            and event.message.stop_reason == "error"
        ]
        self.assertEqual(len(err_events), 2)
        message = err_events[0].message
        self.assertIn("API 未配置", message.error_message or "")
        self.assertIn("API 未配置", message.text)
        self.assertEqual(session.messages[-1].role, "assistant")
        self.assertIsInstance(events[-1], AgentSettledEvent)

    # ─── 文本闭环与事件次序 ──────────────────────────────────

    async def test_text_round_trip_event_order(self) -> None:
        session, _agent, _harness, fake = self._make_session([_stop_event("你好")])

        events = [event async for event in session.prompt("hi")]

        # 首个事件是 AgentStart;AgentEnd 被包装,原始事件不出现。
        self.assertIsInstance(events[0], AgentStartEvent)
        self.assertFalse(any(isinstance(e, AgentEndEvent) for e in events))
        self.assertIsInstance(events[-2], SessionAgentEndEvent)
        self.assertIsInstance(events[-1], AgentSettledEvent)

        self.assertEqual([m.role for m in session.messages], ["user", "assistant"])
        self.assertEqual(session.messages[-1].text, "你好")
        self.assertFalse(session.is_running)
        self.assertEqual(fake.call_count, 1)

    async def test_tool_loop_round_trip(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        session, _agent, _harness, _fake = self._make_session(
            [_tooluse_event(), _stop_event()], registry
        )

        events = [event async for event in session.prompt("hi")]

        self.assertTrue(any(isinstance(e, ToolExecutionStartEvent) for e in events))
        self.assertTrue(any(isinstance(e, ToolExecutionEndEvent) for e in events))
        self.assertEqual(
            [m.role for m in session.messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(session.messages[2].text, "echo:hi")
        self.assertIsInstance(events[-1], AgentSettledEvent)

    # ─── 运行中入队 ──────────────────────────────────────────

    async def test_prompt_while_running_requires_streaming_behavior(self) -> None:
        gate = asyncio.Event()
        registry = ToolRegistry()
        registry.register(_echo_lion_tool(gate))
        session, _agent, _harness, _fake = self._make_session(
            [_tooluse_event(), _stop_event()], registry
        )

        raised = False
        async for event in session.prompt("hi"):
            if isinstance(event, ToolExecutionStartEvent) and not raised:
                self.assertTrue(session.is_running)
                nested = session.prompt("mid-run")
                with self.assertRaises(RuntimeError):
                    await nested.__anext__()
                await nested.aclose()
                raised = True
                gate.set()
        self.assertTrue(raised)
        self.assertFalse(session.is_running)

    async def test_steering_queued_while_running(self) -> None:
        gate = asyncio.Event()
        registry = ToolRegistry()
        registry.register(_echo_lion_tool(gate))
        # 第一轮 toolUse 挂起;steer 入队后放行,steered 消息进入下一轮。
        session, _agent, _harness, _fake = self._make_session(
            [_tooluse_event(), _stop_event("after-steer")], registry
        )

        queue_events: list[QueueUpdateEvent] = []
        async for event in session.prompt("hi"):
            if isinstance(event, ToolExecutionStartEvent) and not queue_events:
                async for queued in session.prompt(
                    "please also do X", streaming_behavior="steer"
                ):
                    self.assertIsInstance(queued, QueueUpdateEvent)
                    queue_events.append(queued)
                gate.set()

        self.assertEqual(len(queue_events), 1)
        self.assertEqual(queue_events[0].steering, ("please also do X",))
        # steered 消息最终进入 transcript。
        user_texts = [m.text for m in session.messages if m.role == "user"]
        self.assertIn("please also do X", user_texts)
        self.assertEqual(session.queued_steering_messages, ())
        self.assertFalse(session.is_running)

    # ─── 取消 ────────────────────────────────────────────────

    async def test_cancel_mid_run_still_settles(self) -> None:
        gate = asyncio.Event()
        registry = ToolRegistry()
        registry.register(_echo_lion_tool(gate))
        # 只脚本一轮 toolUse:工具挂起时取消,第二次模型调用发 aborted。
        session, _agent, _harness, _fake = self._make_session(
            [_tooluse_event()], registry
        )

        events = []
        async for event in session.prompt("hi"):
            events.append(event)
            if isinstance(event, ToolExecutionStartEvent):
                session.cancel()
                gate.set()

        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertIsInstance(events[-2], SessionAgentEndEvent)
        self.assertFalse(session.is_running)
        # 取消后可以继续下一轮(队列/状态未泄漏)。
        self.assertEqual(session.queued_steering_messages, ())

    # ─── 溢出压缩与一次自动重试 ───────────────────────────────

    async def _prime_overflow_history(self, session: LionCodingSession) -> None:
        async for _ in session.prompt("old prompt"):
            pass
        async for _ in session.prompt("keep recent turn"):
            pass

    async def test_context_overflow_compacts_and_retries_once(self) -> None:
        summary = _structured_summary("recovery summary")
        session, _agent, harness, fake = self._make_session(
            [
                _stop_event("old answer"),
                _stop_event("recent answer"),
                _error_event("This model's maximum context length was exceeded."),
                _stop_event(summary),
                _stop_event("recovered answer"),
            ]
        )
        await self._prime_overflow_history(session)
        kernel_events = []
        harness.agent.subscribe(kernel_events.append)

        events = [event async for event in session.prompt("trigger overflow")]

        recovery_events = [
            event
            for event in events
            if isinstance(
                event,
                (
                    SessionAgentEndEvent,
                    CompactionStartEvent,
                    CompactionEndEvent,
                    AutoRetryStartEvent,
                    AutoRetryEndEvent,
                    AgentSettledEvent,
                ),
            )
        ]
        self.assertEqual(
            [event.type for event in recovery_events],
            [
                "session_agent_end",
                "compaction_start",
                "compaction_end",
                "auto_retry_start",
                "session_agent_end",
                "auto_retry_end",
                "agent_settled",
            ],
        )
        self.assertTrue(recovery_events[0].will_retry)
        self.assertFalse(recovery_events[4].will_retry)
        self.assertTrue(recovery_events[2].will_retry)
        self.assertTrue(recovery_events[5].success)
        self.assertEqual(fake.call_count, 5)
        projected = [message.text for message in fake.received_messages[4]]
        self.assertEqual(
            projected[:3],
            [
                f"Previous conversation summary:\n{summary}",
                "keep recent turn",
                "recent answer",
            ],
        )
        self.assertEqual(projected[3], "trigger overflow")

        entries = await self._session_repository.storage_for(
            harness.agent.session_id
        ).read_all()
        compactions = [entry for entry in entries if entry.type == "compaction"]
        self.assertEqual(len(compactions), 1)
        self.assertEqual(compactions[0].summary, summary)
        self.assertEqual(
            [
                event.reason
                for event in kernel_events
                if isinstance(event, KernelCompactionStartedEvent)
            ],
            ["overflow"],
        )
        self.assertEqual(
            [
                (event.reason, event.aborted)
                for event in kernel_events
                if isinstance(event, KernelCompactionCompletedEvent)
            ],
            [("overflow", False)],
        )
        self.assertEqual(
            sum(
                entry.type == "message"
                and isinstance(entry.message, AssistantMessage)
                and entry.message.stop_reason == "error"
                for entry in entries
            ),
            1,
        )

    async def test_overflow_compactor_input_is_bounded_and_smaller(self) -> None:
        summary = _structured_summary("recovery summary")
        old_prompt = "old prompt " + "x" * 20_000
        recent_answer = "recent answer " + "y" * 20_000
        session, _agent, harness, fake = self._make_session(
            [
                _stop_event("old answer"),
                _stop_event(recent_answer),
                _error_event("context window exceeded"),
                _stop_event(summary),
                _stop_event("recovered answer"),
            ]
        )
        async for _ in session.prompt(old_prompt):
            pass
        async for _ in session.prompt("keep recent turn"):
            pass
        harness.composition.runtime.context.effective_window = 2_000

        events = [event async for event in session.prompt("trigger overflow")]

        compaction_end = next(
            event for event in events if isinstance(event, CompactionEndEvent)
        )
        self.assertFalse(compaction_end.aborted)
        original_tokens = estimate_text_tokens(fake.received_systems[2]) + (
            estimate_messages_tokens(fake.received_messages[2])
        )
        compaction_tokens = estimate_text_tokens(fake.received_systems[3]) + (
            estimate_messages_tokens(fake.received_messages[3])
        )
        self.assertLessEqual(compaction_tokens, int(2_000 * 0.85))
        self.assertLess(compaction_tokens, original_tokens // 2)
        self.assertEqual(len(fake.received_messages[3]), 1)
        self.assertNotIn("y" * 1_000, fake.received_messages[3][0].text)

    async def test_context_overflow_compaction_failure_settles(self) -> None:
        session, _agent, _harness, fake = self._make_session(
            [
                _stop_event("old answer"),
                _stop_event("recent answer"),
                _error_event("context window exceeded"),
                _error_event("summary unavailable"),
            ]
        )
        await self._prime_overflow_history(session)

        events = [event async for event in session.prompt("trigger overflow")]

        compaction_end = next(
            event for event in events if isinstance(event, CompactionEndEvent)
        )
        self.assertTrue(compaction_end.aborted)
        self.assertFalse(compaction_end.will_retry)
        self.assertIn("summary unavailable", compaction_end.error_message or "")
        self.assertFalse(
            any(isinstance(event, AutoRetryStartEvent) for event in events)
        )
        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertEqual(fake.call_count, 4)

    async def test_invalid_compaction_summary_preserves_canonical_history(self) -> None:
        session, _agent, harness, fake = self._make_session(
            [
                _stop_event("old answer"),
                _stop_event("recent answer"),
                _error_event("context window exceeded"),
                _stop_event("unstructured summary"),
            ]
        )
        await self._prime_overflow_history(session)

        events = [event async for event in session.prompt("trigger overflow")]

        compaction_end = next(
            event for event in events if isinstance(event, CompactionEndEvent)
        )
        self.assertTrue(compaction_end.aborted)
        self.assertIn("must contain", compaction_end.error_message or "")
        state = await self._session_repository.load(harness.agent.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(len(state.compaction_entries), 0)
        self.assertIn("old prompt", [message.text for message in state.messages])
        self.assertIn("keep recent turn", [message.text for message in state.messages])
        self.assertEqual(fake.call_count, 4)

    async def test_context_overflow_without_old_context_does_not_compact(self) -> None:
        session, _agent, harness, fake = self._make_session(
            [
                _stop_event("only prior answer"),
                _error_event("context window exceeded"),
            ]
        )
        async for _ in session.prompt("only prior prompt"):
            pass

        events = [event async for event in session.prompt("trigger overflow")]

        compaction_end = next(
            event for event in events if isinstance(event, CompactionEndEvent)
        )
        self.assertTrue(compaction_end.aborted)
        self.assertFalse(compaction_end.will_retry)
        self.assertFalse(
            any(isinstance(event, AutoRetryStartEvent) for event in events)
        )
        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertEqual(fake.call_count, 2)
        state = await self._session_repository.load(harness.agent.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(len(state.compaction_entries), 0)

    async def test_cancel_during_overflow_compaction_does_not_retry(self) -> None:
        session, _agent, harness, fake = self._make_session(
            [
                _stop_event("old answer"),
                _stop_event("recent answer"),
                _error_event("context length exceeded"),
            ]
        )
        await self._prime_overflow_history(session)

        compaction_started = asyncio.Event()

        class BlockingCompactor:
            async def summarize(self, _request) -> str:
                compaction_started.set()
                await asyncio.Event().wait()
                raise AssertionError("取消后不应继续摘要")

        harness.composition.runtime.context.replace_context_compactor(
            BlockingCompactor()
        )

        async def collect_events():
            return [event async for event in session.prompt("trigger overflow")]

        collector = asyncio.create_task(collect_events())
        await asyncio.wait_for(compaction_started.wait(), timeout=1)
        session.cancel()
        events = await asyncio.wait_for(collector, timeout=1)

        compaction_end = next(
            event for event in events if isinstance(event, CompactionEndEvent)
        )
        self.assertTrue(compaction_end.aborted)
        self.assertFalse(compaction_end.will_retry)
        self.assertFalse(
            any(isinstance(event, AutoRetryStartEvent) for event in events)
        )
        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertEqual(fake.call_count, 3)
        state = await self._session_repository.load(harness.agent.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(len(state.compaction_entries), 0)

    async def test_context_overflow_retry_failure_is_terminal(self) -> None:
        summary = _structured_summary("recovery summary")
        session, _agent, _harness, fake = self._make_session(
            [
                _stop_event("old answer"),
                _stop_event("recent answer"),
                _error_event("too many tokens"),
                _stop_event(summary),
                _error_event("context limit still exceeded"),
            ]
        )
        await self._prime_overflow_history(session)

        events = [event async for event in session.prompt("trigger overflow")]

        retry_starts = [
            event for event in events if isinstance(event, AutoRetryStartEvent)
        ]
        retry_end = next(
            event for event in events if isinstance(event, AutoRetryEndEvent)
        )
        agent_ends = [
            event for event in events if isinstance(event, SessionAgentEndEvent)
        ]
        self.assertEqual(len(retry_starts), 1)
        self.assertFalse(retry_end.success)
        self.assertEqual(retry_end.final_error, "context limit still exceeded")
        self.assertEqual([event.will_retry for event in agent_ends], [True, False])
        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertEqual(fake.call_count, 5)

    async def test_non_overflow_provider_error_does_not_retry(self) -> None:
        session, _agent, _harness, fake = self._make_session(
            [
                _error_event("service unavailable"),
            ]
        )

        events = [event async for event in session.prompt("hello")]

        self.assertFalse(
            any(
                isinstance(event, (CompactionStartEvent, AutoRetryStartEvent))
                for event in events
            )
        )
        agent_end = next(
            event for event in events if isinstance(event, SessionAgentEndEvent)
        )
        self.assertFalse(agent_end.will_retry)
        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertEqual(fake.call_count, 1)

    async def test_generic_limit_error_does_not_trigger_overflow_recovery(self) -> None:
        session, _agent, _harness, fake = self._make_session(
            [
                _error_event("Requests per minute exceeded the limit"),
            ]
        )

        events = [event async for event in session.prompt("hello")]

        agent_end = next(
            event for event in events if isinstance(event, SessionAgentEndEvent)
        )
        self.assertFalse(agent_end.will_retry)
        self.assertFalse(
            any(
                isinstance(event, (CompactionStartEvent, AutoRetryStartEvent))
                for event in events
            )
        )
        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertEqual(fake.call_count, 1)

    # ─── Durable Session 一致性 ──────────────────────────────

    async def test_messages_match_jsonl_session(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        session, _agent, harness, _fake = self._make_session(
            [_tooluse_event(), _stop_event()], registry
        )

        async for _ in session.prompt("hi"):
            pass
        transcript = session.messages
        await session.aclose()

        state = await self._session_repository.load(harness.agent.session_id)
        self.assertIsNotNone(state)
        self.assertEqual([m.role for m in state.messages], [m.role for m in transcript])
        self.assertEqual(state.messages[-1].text, transcript[-1].text)

    async def test_configure_provider_keeps_backend_binding(self) -> None:
        from core.fakes import FakeProvider

        session, agent, harness, original_provider = self._make_session(
            [_stop_event("old")]
        )
        original_runtime = harness.composition.runtime.conversation
        replacement_provider = FakeProvider([_stop_event("new")])

        with patch("full_agent.create_provider", return_value=replacement_provider):
            session.configure_provider(api_key="new-key")

        self.assertIs(harness.composition.runtime.conversation, original_runtime)
        self.assertIs(session._backend, agent)
        async for _ in session.prompt("hello"):
            pass
        self.assertEqual(original_provider.call_count, 0)
        self.assertEqual(replacement_provider.call_count, 1)
        self.assertEqual(session.messages[-1].text, "new")

    async def test_configure_provider_rejects_unsettled_session(self) -> None:
        session, _agent, harness, provider = self._make_session([])
        config = harness.agent.provider_config()
        session._running = True
        try:
            with (
                patch("full_agent.create_provider") as create,
                self.assertRaisesRegex(RuntimeError, "会话运行中"),
            ):
                session.configure_provider(api_key="new-key")
        finally:
            session._running = False

        create.assert_not_called()
        self.assertIs(harness.composition.runtime.conversation.provider, provider)
        self.assertEqual(harness.agent.provider_config(), config)

    # ─── Thinking 档位 ────────────────────────────────────────

    async def test_thinking_level_defaults_and_available(self) -> None:
        session, _agent, _harness, _fake = self._make_session([_stop_event()])
        self.assertEqual(session.thinking_level, "off")
        self.assertEqual(
            tuple(session.available_thinking_levels),
            ("off", "minimal", "low", "medium", "high", "xhigh"),
        )

    async def test_set_thinking_level_rebuilds_provider_with_level(self) -> None:
        from core.fakes import FakeProvider

        session, _agent, harness, _fake = self._make_session([_stop_event()])
        replacement = FakeProvider([])
        with patch("full_agent.create_provider", return_value=replacement) as mock:
            session.set_thinking_level("high")

        # Core 路径按档位热重建 Provider。
        self.assertEqual(mock.call_args.kwargs.get("thinking_level"), "high")
        self.assertIs(harness.composition.runtime.conversation.provider, replacement)
        self.assertEqual(session.thinking_level, "high")

    async def test_cycle_thinking_level_advances_and_wraps(self) -> None:
        from core.fakes import FakeProvider

        session, _agent, _harness, _fake = self._make_session([_stop_event()])
        with patch("full_agent.create_provider", return_value=FakeProvider([])):
            self.assertEqual(session.thinking_level, "off")
            self.assertEqual(session.cycle_thinking_level(), "minimal")
            self.assertEqual(session.cycle_thinking_level(), "low")
            self.assertEqual(session.thinking_level, "low")
            session.set_thinking_level("xhigh")
            self.assertEqual(session.cycle_thinking_level(), "off")

    async def test_set_thinking_level_persists_entry(self) -> None:
        from core.fakes import FakeProvider

        session, _agent, harness, _fake = self._make_session([_stop_event("ok")])
        async for _ in session.prompt("hi"):
            pass
        with patch("full_agent.create_provider", return_value=FakeProvider([])):
            session.set_thinking_level("high")
        self.assertEqual(session.thinking_level, "high")

        await session.aclose()
        state = await self._session_repository.load(harness.agent.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.thinking_level, "high")

    async def test_set_thinking_level_rejects_unknown(self) -> None:
        session, _agent, _harness, _fake = self._make_session([_stop_event()])
        with self.assertRaises(ValueError):
            session.set_thinking_level("ultra")
        # 被拒后档位不变。
        self.assertEqual(session.thinking_level, "off")

    async def test_thinking_switch_rejects_unsettled_session(self) -> None:
        session, _agent, harness, provider = self._make_session([])
        session._running = True
        try:
            with patch("full_agent.create_provider") as create:
                with self.assertRaisesRegex(RuntimeError, "会话运行中"):
                    session.set_thinking_level("high")
                with self.assertRaisesRegex(RuntimeError, "会话运行中"):
                    session.cycle_thinking_level()
        finally:
            session._running = False

        create.assert_not_called()
        self.assertIs(harness.composition.runtime.conversation.provider, provider)
        self.assertEqual(session.thinking_level, "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)
