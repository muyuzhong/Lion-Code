"""Supervisor 的公开运行、重试和 checkpoint 契约测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lion_code.core.events import (
    AgentStartEvent,
    CompactionStartedEvent,
)
from lion_code.supervisor import (
    CheckpointError,
    Goal,
    JsonCheckpointStore,
    RetryPolicy,
    Supervisor,
    SupervisorState,
    VolatileCheckpointStore,
)


@dataclass
class _Result:
    session_id: str
    stop_reason: str
    error: str | None = None


class _FakeAgent:
    def __init__(
        self,
        session_id: str,
        results: list[_Result],
        events: list[Any] | None = None,
        wait_for_cancel: bool = False,
    ) -> None:
        self._session_id = session_id
        self._results = results
        self._events = events or []
        self._wait_for_cancel = wait_for_cancel
        self._listeners: list[Any] = []
        self.restore_calls: list[str] = []
        self.run_prompts: list[str] = []
        self.closed = False
        self.cancelled = False
        self.after_event: Any = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def subscribe(self, listener: Any):
        self._listeners.append(listener)

        def unsubscribe() -> None:
            self._listeners.remove(listener)

        return unsubscribe

    async def run(self, prompt: str, *, timeout: float | None = None) -> _Result:
        del timeout
        self.run_prompts.append(prompt)
        for event in self._events:
            for listener in tuple(self._listeners):
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            if self.after_event is not None:
                self.after_event()
        if self._wait_for_cancel:
            while not self.cancelled:
                await asyncio.sleep(0)
        if self.cancelled:
            return _Result(self._session_id, "aborted", "cancelled by test")
        return self._results.pop(0)

    async def restore(self, session_id: str) -> bool:
        self.restore_calls.append(session_id)
        return True

    def cancel(self) -> None:
        self.cancelled = True

    async def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self.agents = agents

    def __call__(self) -> _FakeAgent:
        return self.agents.pop(0)


class _RecordingScheduler:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def wait(self, delay_seconds: float) -> None:
        self.delays.append(delay_seconds)


class _BlockingScheduler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._never = asyncio.Event()

    async def wait(self, _delay_seconds: float) -> None:
        self.started.set()
        await self._never.wait()


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    def test_control_contract_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            Goal("")
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)
        with self.assertRaises(ValueError):
            SupervisorState(
                goal_id="invalid-phase",
                goal="control",
                phase="recovery",
                status="pending",
            )

        state = SupervisorState(goal_id="strict", goal="control")
        payload = state.to_dict()
        payload["next_delay_seconds"] = -1
        with self.assertRaises(CheckpointError):
            SupervisorState.from_dict(payload)
        payload = state.to_dict()
        payload["created_at"] = float("inf")
        with self.assertRaises(CheckpointError):
            SupervisorState.from_dict(payload)

    async def test_runs_public_agent_and_persists_control_state_only(self) -> None:
        agent = _FakeAgent(
            "session-1",
            [_Result("session-1", "completed")],
            [AgentStartEvent()],
        )
        store = VolatileCheckpointStore()
        supervisor = Supervisor(
            agent_factory=_Factory([agent]),
            goal="写一个最小实现",
            retry_policy=RetryPolicy(max_attempts=1),
            checkpoint_store=store,
        )

        result = await supervisor.run()

        self.assertTrue(result.succeeded)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.attempt, 1)
        self.assertEqual(agent.run_prompts, ["写一个最小实现"])
        self.assertTrue(agent.closed)
        state = await store.load(supervisor.goal.id)
        assert state is not None
        self.assertEqual(
            set(state.to_dict()),
            {
                "goal_id",
                "goal",
                "phase",
                "status",
                "attempt",
                "session_id",
                "retry_count",
                "last_stop_reason",
                "last_error",
                "next_delay_seconds",
                "created_at",
                "updated_at",
                "next_run_at",
            },
        )
        self.assertNotIn("final_text", state.to_dict())
        self.assertNotIn("messages", state.to_dict())

    async def test_public_events_update_execution_phase(self) -> None:
        phases: list[str] = []
        agent = _FakeAgent(
            "session-events",
            [_Result("session-events", "completed")],
            [AgentStartEvent(), CompactionStartedEvent(reason="overflow")],
        )
        supervisor = Supervisor(
            agent_factory=_Factory([agent]),
            goal=Goal(id="events", prompt="observe events"),
            retry_policy=RetryPolicy(max_attempts=1),
            checkpoint_store=VolatileCheckpointStore(),
        )
        agent.after_event = lambda: phases.append(supervisor.state.phase)  # type: ignore[union-attr]

        await supervisor.run()

        self.assertEqual(phases, ["running", "recovery"])

    async def test_retry_policy_waits_and_stops_at_attempt_limit(self) -> None:
        first = _FakeAgent("session-1", [_Result("session-1", "timeout", "slow")])
        second = _FakeAgent("session-2", [_Result("session-2", "completed")])
        scheduler = _RecordingScheduler()
        supervisor = Supervisor(
            agent_factory=_Factory([first, second]),
            goal=Goal(id="retry", prompt="retry once"),
            retry_policy=RetryPolicy(
                max_attempts=2,
                initial_delay_seconds=0.25,
                retryable_stop_reasons=frozenset({"timeout"}),
            ),
            checkpoint_store=VolatileCheckpointStore(),
            scheduler=scheduler,
        )

        result = await supervisor.run()

        self.assertTrue(result.succeeded)
        self.assertEqual(result.attempt, 2)
        self.assertEqual(len(scheduler.delays), 1)
        self.assertAlmostEqual(scheduler.delays[0], 0.25, places=3)
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    async def test_default_scheduler_handles_retry_delay(self) -> None:
        first = _FakeAgent(
            "session-default-1", [_Result("session-default-1", "timeout")]
        )
        second = _FakeAgent(
            "session-default-2", [_Result("session-default-2", "completed")]
        )
        supervisor = Supervisor(
            agent_factory=_Factory([first, second]),
            goal="use default scheduler",
            retry_policy=RetryPolicy(
                max_attempts=2,
                initial_delay_seconds=0.001,
                retryable_stop_reasons=frozenset({"timeout"}),
            ),
            checkpoint_store=VolatileCheckpointStore(),
        )

        result = await supervisor.run()

        self.assertTrue(result.succeeded)
        self.assertEqual(result.attempt, 2)

    async def test_loaded_running_checkpoint_restores_session_before_resume(
        self,
    ) -> None:
        goal = Goal(id="resume", prompt="resume work")
        store = VolatileCheckpointStore()
        await store.save(
            SupervisorState(
                goal_id=goal.id,
                goal=goal.prompt,
                phase="running",
                status="running",
                attempt=1,
                session_id="durable-session",
            )
        )
        agent = _FakeAgent("new-session", [_Result("new-session", "completed")])
        supervisor = Supervisor(
            agent_factory=_Factory([agent]),
            goal=goal,
            retry_policy=RetryPolicy(max_attempts=2),
            checkpoint_store=store,
        )

        result = await supervisor.run()

        self.assertTrue(result.succeeded)
        self.assertEqual(result.attempt, 2)
        self.assertEqual(agent.restore_calls, ["durable-session"])
        self.assertEqual(result.session_id, "new-session")

    async def test_cancel_during_retry_wait_returns_terminal_result(self) -> None:
        goal = Goal(id="cancel-wait", prompt="cancel while waiting")
        store = VolatileCheckpointStore()
        now = 100.0
        await store.save(
            SupervisorState(
                goal_id=goal.id,
                goal=goal.prompt,
                phase="retry_wait",
                status="pending",
                attempt=1,
                retry_count=1,
                next_delay_seconds=10.0,
                created_at=now,
                updated_at=now,
                next_run_at=now + 10.0,
            )
        )
        scheduler = _BlockingScheduler()
        supervisor = Supervisor(
            agent_factory=lambda: _FakeAgent("unused", []),
            goal=goal,
            checkpoint_store=store,
            scheduler=scheduler,
            clock=lambda: now,
        )

        task = asyncio.create_task(supervisor.run())
        await scheduler.started.wait()
        supervisor.cancel()
        result = await task

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.stop_reason, "cancelled")

    async def test_factory_failure_is_a_terminal_control_result(self) -> None:
        def failing_factory() -> Any:
            raise RuntimeError("factory unavailable")

        supervisor = Supervisor(
            agent_factory=failing_factory,
            goal="factory failure",
            retry_policy=RetryPolicy(max_attempts=3),
            checkpoint_store=VolatileCheckpointStore(),
        )

        result = await supervisor.run()

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.stop_reason, "agent_factory_error")
        self.assertEqual(result.attempt, 1)

    async def test_cancellation_is_terminal_and_never_retried(self) -> None:
        agent = _FakeAgent(
            "session-cancel",
            [_Result("session-cancel", "timeout")],
            wait_for_cancel=True,
        )
        supervisor = Supervisor(
            agent_factory=_Factory([agent]),
            goal="cancel work",
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=10,
                retryable_stop_reasons=frozenset({"timeout", "aborted"}),
            ),
            checkpoint_store=VolatileCheckpointStore(),
        )

        task = asyncio.create_task(supervisor.run())
        while supervisor.state is None or supervisor.state.status != "running":
            await asyncio.sleep(0)
        supervisor.cancel()
        result = await task

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.attempt, 1)
        self.assertTrue(agent.cancelled)

    async def test_json_checkpoint_is_atomic_shape_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCheckpointStore(directory)
            state = SupervisorState(goal_id="json", goal="persist control")
            await store.save(state)
            path = Path(directory) / "json.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload), set(state.to_dict()))
            self.assertEqual((await store.load("json")), state)

            payload["messages"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(CheckpointError):
                await store.load("json")

    async def test_terminal_failure_does_not_create_retry(self) -> None:
        agent = _FakeAgent("session-fail", [_Result("session-fail", "max_turns")])
        scheduler = _RecordingScheduler()
        supervisor = Supervisor(
            agent_factory=_Factory([agent]),
            goal="terminal failure",
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=1,
                retryable_stop_reasons=frozenset({"timeout"}),
            ),
            checkpoint_store=VolatileCheckpointStore(),
            scheduler=scheduler,
        )

        result = await supervisor.run()

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.stop_reason, "max_turns")
        self.assertEqual(scheduler.delays, [])


if __name__ == "__main__":
    unittest.main()
