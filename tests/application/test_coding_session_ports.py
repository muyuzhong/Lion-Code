"""Application policy tests driven entirely by the application backend port."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

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
from lion_code.core import AgentEndEvent, AgentStartEvent, AssistantMessage
from lion_code.core.events import MessageEndEvent

from .fakes import FakeCodingSessionBackend


def _assistant(
    text: str,
    *,
    stop_reason: str = "stop",
    error_message: str | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        model="fake-model",
        content=text,
        stop_reason=stop_reason,
        error_message=error_message,
    )


def _run_events(message: AssistantMessage) -> list:
    return [
        AgentStartEvent(),
        MessageEndEvent(message=message),
        AgentEndEvent(),
    ]


async def _collect(stream) -> list:
    return [event async for event in stream]


class LionCodingSessionPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_bridge_preserves_settled_semantics(self) -> None:
        backend = FakeCodingSessionBackend(
            prompt_scripts=[_run_events(_assistant("done"))]
        )
        session = LionCodingSession(backend)

        events = await _collect(session.prompt("hello"))

        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertIsInstance(events[-2], SessionAgentEndEvent)
        self.assertFalse(session.is_running)
        self.assertEqual(backend.prompt_calls, 1)

    async def test_steering_follow_up_and_queue_snapshot_use_text_only(self) -> None:
        backend = FakeCodingSessionBackend(wait_for_cancel=True)
        session = LionCodingSession(backend)
        running = asyncio.create_task(_collect(session.prompt("first")))
        await backend.prompt_started.wait()

        steering = await _collect(
            session.prompt("steer me", streaming_behavior="steer")
        )
        follow_up = await _collect(
            session.prompt("follow me", streaming_behavior="follow_up")
        )

        self.assertEqual(steering, [QueueUpdateEvent(steering=("steer me",))])
        self.assertEqual(
            follow_up,
            [QueueUpdateEvent(steering=("steer me",), follow_up=("follow me",))],
        )
        self.assertEqual(session.queued_steering_messages, ("steer me",))
        self.assertEqual(session.queued_follow_up_messages, ("follow me",))

        session.cancel()
        await running
        self.assertEqual(backend.cancel_calls, 1)

    async def test_cancel_finishes_the_event_bridge_without_retry(self) -> None:
        backend = FakeCodingSessionBackend(wait_for_cancel=True)
        session = LionCodingSession(backend)
        running = asyncio.create_task(_collect(session.prompt("hello")))
        await backend.prompt_started.wait()

        session.cancel()
        events = await running

        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertFalse(session.is_running)

    async def test_overflow_compacts_then_retries_once(self) -> None:
        overflow = _assistant(
            "overflow",
            stop_reason="error",
            error_message="context length exceeded",
        )
        backend = FakeCodingSessionBackend(
            prompt_scripts=[_run_events(overflow)],
            continue_scripts=[_run_events(_assistant("recovered"))],
        )
        session = LionCodingSession(backend)

        events = await _collect(session.prompt("hello"))
        event_types = [type(event) for event in events]

        self.assertEqual(backend.compact_calls, 1)
        self.assertEqual(backend.continue_calls, 1)
        self.assertIn(CompactionStartEvent, event_types)
        self.assertIn(CompactionEndEvent, event_types)
        self.assertIn(AutoRetryStartEvent, event_types)
        self.assertEqual(
            [event for event in events if isinstance(event, AutoRetryEndEvent)],
            [AutoRetryEndEvent(success=True, attempt=1)],
        )
        self.assertIsInstance(events[-1], AgentSettledEvent)

    async def test_abort_during_retry_prevents_continue(self) -> None:
        overflow = _assistant(
            "overflow",
            stop_reason="error",
            error_message="context window exceeded",
        )
        backend = FakeCodingSessionBackend(prompt_scripts=[_run_events(overflow)])
        session = LionCodingSession(backend)

        events = []
        async for event in session.prompt("hello"):
            events.append(event)
            if isinstance(event, AutoRetryStartEvent):
                session.cancel()

        self.assertEqual(backend.compact_calls, 1)
        self.assertEqual(backend.continue_calls, 0)
        self.assertEqual(
            [event for event in events if isinstance(event, AutoRetryEndEvent)],
            [AutoRetryEndEvent(success=False, attempt=1, final_error="aborted")],
        )
        self.assertIsInstance(events[-1], AgentSettledEvent)

    async def test_session_and_settings_operations_are_port_calls(self) -> None:
        backend = FakeCodingSessionBackend(
            cwd=Path("D:/workspace"),
            sessions=[{"id": "s1"}],
        )
        session = LionCodingSession(backend)

        self.assertEqual(session.cwd, Path("D:/workspace"))
        self.assertEqual(await session.list_sessions(), [{"id": "s1"}])
        self.assertTrue(await session.resume("s1"))
        self.assertTrue(await session.restore_latest())
        await session.new_session()
        await session.handoff_session()
        await session.compact()
        session.configure_provider(model="new-model")
        self.assertEqual(session.model, "new-model")
        self.assertEqual(session.get_provider_config(), {"model": "new-model"})
        self.assertEqual(session.set_thinking_level("low"), "low")
        self.assertEqual(session.cycle_thinking_level(), "medium")
        await session.aclose()

        self.assertEqual(
            [operation[0] for operation in backend.session_operations],
            ["list", "resume", "restore_latest", "new", "handoff", "compact"],
        )
        self.assertTrue(backend.closed)


if __name__ == "__main__":
    unittest.main()
