from __future__ import annotations

import asyncio

import pytest

import lion_code.memory_runtime.coordinator as coordinator_module
from lion_code.memory import MemoryPrefetch, RelevantMemory
from lion_code.memory_runtime import (
    MemoryContextPolicy,
    MemoryCoordinator,
)


class _QueryService:
    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 256,
    ) -> str:
        return "{}"


def _memory(path: str, content: str = "body") -> RelevantMemory:
    return RelevantMemory(path, content, 0, "")


def _completed_prefetch(memories: list[RelevantMemory]) -> MemoryPrefetch:
    async def complete() -> list[RelevantMemory]:
        return memories

    return MemoryPrefetch(asyncio.create_task(complete()))


@pytest.mark.asyncio
async def test_collects_deduplicates_and_keeps_recent_active_overlays(monkeypatch) -> None:
    memories = [_memory("a.md"), _memory("a.md"), _memory("b.md"), _memory("c.md")]
    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: _completed_prefetch(memories),
    )
    coordinator = MemoryCoordinator(
        query_service=_QueryService(),
        policy=MemoryContextPolicy(max_active_memories=2, max_session_bytes=100),
    )

    coordinator.begin_turn("two words")
    await asyncio.sleep(0)
    coordinator.collect_ready()

    assert [item.path for item in coordinator.active_overlays] == ["c.md", "b.md"]
    assert coordinator.already_surfaced == frozenset({"a.md", "b.md", "c.md"})
    assert coordinator.session_bytes == 12


@pytest.mark.asyncio
async def test_session_budget_stops_new_memories(monkeypatch) -> None:
    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: _completed_prefetch(
            [_memory("a.md", "1234"), _memory("b.md", "5678")]
        ),
    )
    coordinator = MemoryCoordinator(
        query_service=_QueryService(),
        policy=MemoryContextPolicy(max_session_bytes=5),
    )

    coordinator.begin_turn("two words")
    await asyncio.sleep(0)
    coordinator.collect_ready()

    assert [item.path for item in coordinator.active_overlays] == ["a.md"]
    assert coordinator.session_bytes == 4
    assert "b.md" in coordinator.already_surfaced


@pytest.mark.asyncio
async def test_failed_prefetch_is_non_blocking(monkeypatch) -> None:
    async def fail() -> list[RelevantMemory]:
        raise RuntimeError("query failed")

    monkeypatch.setattr(
        coordinator_module,
        "start_memory_prefetch",
        lambda *_args, **_kwargs: MemoryPrefetch(asyncio.create_task(fail())),
    )
    coordinator = MemoryCoordinator(query_service=_QueryService())

    coordinator.begin_turn("two words")
    await asyncio.sleep(0)
    coordinator.collect_ready()

    assert coordinator.active_overlays == ()
