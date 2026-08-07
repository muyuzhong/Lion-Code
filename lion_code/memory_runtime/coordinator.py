"""协调非阻塞 Memory 预取、去重、预算和活跃 Overlay。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lion_code.memory import MemoryPrefetch, start_memory_prefetch
from lion_code.memory_runtime.query import TextQueryService
from lion_code.memory_runtime.types import MemoryContextPolicy, MemoryOverlay


@dataclass(slots=True)
class _PendingPrefetch:
    handle: MemoryPrefetch
    generation: int


class MemoryCoordinator:
    """让 Memory 召回独立于模型主调用运行，并维护会话级状态。"""

    def __init__(
        self,
        *,
        query_service: TextQueryService | None,
        policy: MemoryContextPolicy | None = None,
    ) -> None:
        self._query_service = query_service
        self._policy = policy or MemoryContextPolicy()
        self._pending: _PendingPrefetch | None = None
        self._active: dict[str, MemoryOverlay] = {}
        self._already_surfaced: set[str] = set()
        self._session_bytes = 0
        self._generation = 0

    @property
    def active_overlays(self) -> tuple[MemoryOverlay, ...]:
        """按最近召回优先返回当前活跃 Overlay。"""

        return tuple(reversed(tuple(self._active.values())))

    @property
    def session_bytes(self) -> int:
        return self._session_bytes

    @property
    def already_surfaced(self) -> frozenset[str]:
        return frozenset(self._already_surfaced)

    def set_query_service(self, service: TextQueryService | None) -> None:
        """替换 Side Query 实现，并取消仍引用旧 Provider 的预取。"""

        self.cancel_pending()
        self._query_service = service

    def begin_turn(self, user_message: str) -> None:
        """收集上一轮结果，并为当前用户输入启动零等待预取。"""

        self.collect_ready()
        self._discard_pending()
        if (
            self._query_service is None
            or self._session_bytes >= self._policy.max_session_bytes
        ):
            return
        handle = start_memory_prefetch(
            user_message,
            self._complete,
            set(self._already_surfaced),
            self._session_bytes,
        )
        if handle is not None:
            self._pending = _PendingPrefetch(handle, self._generation)

    def collect_ready(self) -> None:
        """非阻塞收集已完成预取；失败或过期结果不影响主模型。"""

        pending = self._pending
        if pending is None or not pending.handle.settled or pending.handle.consumed:
            return
        pending.handle.consumed = True
        self._pending = None
        if pending.generation != self._generation:
            _consume_task_result(pending.handle.task)
            return
        try:
            memories = pending.handle.task.result()
        except (asyncio.CancelledError, Exception):
            return

        for memory in memories:
            if memory.path in self._already_surfaced:
                continue
            content = (
                f"{memory.header}\n\n{memory.content}"
                if memory.header
                else memory.content
            )
            byte_size = len(content.encode("utf-8"))
            if self._session_bytes + byte_size > self._policy.max_session_bytes:
                self._already_surfaced.add(memory.path)
                continue
            if self._policy.max_active_memories <= 0:
                self._already_surfaced.add(memory.path)
                continue
            if len(self._active) >= self._policy.max_active_memories:
                oldest_path = next(iter(self._active))
                del self._active[oldest_path]
            self._active[memory.path] = MemoryOverlay(
                path=memory.path,
                content=content,
                byte_size=byte_size,
            )
            self._already_surfaced.add(memory.path)
            self._session_bytes += byte_size

    def cancel_pending(self) -> None:
        """取消当前查询并使其结果失效，但保留已激活的 Memory。"""

        self._generation += 1
        self._discard_pending()

    def reset(self) -> None:
        """切换 Session 时清除所有 Memory 运行态。"""

        self.cancel_pending()
        self._active.clear()
        self._already_surfaced.clear()
        self._session_bytes = 0

    def invalidate(self, filenames: list[str]) -> None:
        """Dream 修改文件后淘汰对应 Overlay，并允许下一轮重新召回。"""

        self.cancel_pending()
        targets = set(filenames)
        target_names = {name.replace("\\", "/").rsplit("/", 1)[-1] for name in targets}
        for path in tuple(self._active):
            if (
                path in targets
                or path.replace("\\", "/").rsplit("/", 1)[-1] in target_names
            ):
                del self._active[path]
        self._already_surfaced = {
            path
            for path in self._already_surfaced
            if path not in targets
            and path.replace("\\", "/").rsplit("/", 1)[-1] not in target_names
        }
        self._session_bytes = sum(item.byte_size for item in self._active.values())

    async def close(self) -> None:
        """取消并回收预取任务，避免退出时遗留异步任务。"""

        pending = self._pending
        self.cancel_pending()
        if pending is not None:
            await asyncio.gather(pending.handle.task, return_exceptions=True)

    async def _complete(self, system: str, user: str) -> str:
        service = self._query_service
        if service is None:
            return ""
        return await service.complete(system=system, user=user)

    def _discard_pending(self) -> None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        task = pending.handle.task
        if not task.done():
            task.cancel()
        task.add_done_callback(_consume_task_result)


def _consume_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        pass
