from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

import lion_code.memory_runtime.coordinator as coordinator_module
from lion_code.memory import MemoryPrefetch, RelevantMemory
from lion_code.memory_runtime import MemoryCoordinator, MemoryOverlay


class _QueryService:
    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str:
        return "{}"


@pytest.mark.asyncio
async def test_reset_rejects_a_stale_generation(monkeypatch) -> None:
    release = asyncio.Event()

    async def ignore_cancellation() -> list[RelevantMemory]:
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return [RelevantMemory("old.md", "old", 0, "")]

    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: MemoryPrefetch(
            asyncio.create_task(ignore_cancellation())
        ),
    )
    coordinator = MemoryCoordinator(query_service=_QueryService())
    coordinator.begin_turn("session one")
    await asyncio.sleep(0)

    coordinator.reset()
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    coordinator.collect_ready()

    assert coordinator.active_overlays == ()
    assert coordinator.already_surfaced == frozenset()


@pytest.mark.asyncio
async def test_close_cancels_and_reaps_pending_task(monkeypatch) -> None:
    started = asyncio.Event()
    finalized = asyncio.Event()

    async def wait_forever() -> list[RelevantMemory]:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    handle = MemoryPrefetch(asyncio.create_task(wait_forever()))
    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: handle,
    )
    coordinator = MemoryCoordinator(query_service=_QueryService())
    coordinator.begin_turn("two words")
    await started.wait()

    await coordinator.close()

    assert handle.task.done()
    assert finalized.is_set()


def test_invalidate_removes_changed_overlay_and_reopens_path() -> None:
    coordinator = MemoryCoordinator(query_service=None)
    coordinator._active["C:/memory/project_changed.md"] = MemoryOverlay(
        "C:/memory/project_changed.md", "old", 3
    )
    coordinator._active["C:/memory/project_other.md"] = MemoryOverlay(
        "C:/memory/project_other.md", "other", 5
    )
    coordinator._already_surfaced.update(coordinator._active)
    coordinator._session_bytes = 8

    coordinator.invalidate(["project_changed.md"])

    assert [item.path for item in coordinator.active_overlays] == [
        "C:/memory/project_other.md"
    ]
    assert "C:/memory/project_changed.md" not in coordinator.already_surfaced
    assert coordinator.session_bytes == 5


def test_core_abort_cancels_memory_and_harness_together() -> None:
    from lion_code.agent_runtime import AgentRuntimeCoordinator

    host = Mock()
    host._memory_coordinator = Mock()
    host._terminal_output = False
    runtime = Mock()
    coordinator = AgentRuntimeCoordinator.__new__(AgentRuntimeCoordinator)
    coordinator._host = host
    coordinator._runtime = runtime
    coordinator._core_compaction_task = None
    coordinator._terminal_renderer = None
    coordinator._terminal_renderer_unsubscribe = None
    coordinator._observer_unsubscribers = []

    coordinator.abort()

    host._memory_coordinator.cancel_pending.assert_called_once_with()
    runtime.cancel.assert_called_once_with()
