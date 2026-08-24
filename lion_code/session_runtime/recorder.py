"""把 Core Agent 事件记录为 append-only Session Entry。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from lion_code.core.events import AgentEvent, MessageEndEvent
from lion_code.core.messages import AgentMessage
from lion_code.core.session import (
    CompactionEntry,
    JsonlSessionStorage,
    LabelEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionEntry,
    SessionInfoEntry,
    SessionState,
    ThinkingLevelChangeEntry,
)


class SessionRecorder:
    """按事件到达顺序串行追加会话记录，不依赖任何 UI。"""

    def __init__(
        self,
        *,
        session_id: str,
        model: str,
        thinking_level: str | None,
        cwd: Path,
        storage: JsonlSessionStorage,
    ) -> None:
        self.session_id = session_id
        self.model = model
        self.thinking_level = thinking_level
        self.cwd = cwd
        self.storage = storage

        self._parent_id: str | None = None
        self._context_entry_ids: list[str] = []
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> None:
        """恢复现有写入位置；新会话尚无可写文件时不产生磁盘文件。"""
        async with self._lock:
            await self._initialize_unlocked()

    async def handle(self, event: AgentEvent) -> None:
        """只持久化完成态消息；增量渲染事件不进入 durable history。"""
        if isinstance(event, MessageEndEvent):
            await self.record_message(event.message)

    async def record_message(self, message: AgentMessage) -> MessageEntry:
        async with self._lock:
            await self._initialize_unlocked()
            await self._ensure_initial_entries_unlocked()
            entry = MessageEntry(parent_id=self._parent_id, message=message)
            await self._append_unlocked(entry)
            self._context_entry_ids.append(entry.id)
            return entry

    async def record_label(self, label: str) -> LabelEntry | None:
        """追加会话标题，并避免重复写入相同标题。"""
        async with self._lock:
            await self._initialize_unlocked()
            entries = await self.storage.read_all()
            state = SessionState.from_entries(entries)
            if state.label == label:
                return None
            entry = LabelEntry(parent_id=self._parent_id, label=label)
            await self._append_unlocked(entry)
            return entry

    async def record_model_change(self, model: str) -> ModelChangeEntry | None:
        async with self._lock:
            await self._initialize_unlocked()
            if model == self.model:
                return None
            self.model = model
            if self._parent_id is None:
                # 全新会话尚未落盘：不单独写配置 Entry，初始 ModelChangeEntry 会带当前模型。
                return None
            entry = ModelChangeEntry(parent_id=self._parent_id, model=model)
            await self._append_unlocked(entry)
            return entry

    async def record_thinking_level_change(
        self,
        thinking_level: str | None,
    ) -> ThinkingLevelChangeEntry | None:
        async with self._lock:
            await self._initialize_unlocked()
            if thinking_level == self.thinking_level:
                return None
            self.thinking_level = thinking_level
            if self._parent_id is None:
                # 同 record_model_change：未落盘会话不产生仅配置的空文件。
                return None
            entry = ThinkingLevelChangeEntry(
                parent_id=self._parent_id,
                thinking_level=thinking_level,
            )
            await self._append_unlocked(entry)
            return entry

    async def record_compaction(
        self,
        *,
        summary: str,
        replaces_entry_ids: list[str] | None = None,
    ) -> CompactionEntry:
        """记录上下文替换，同时保留被替换的原始 Entry。"""
        async with self._lock:
            await self._initialize_unlocked()
            replaced = list(
                self._context_entry_ids
                if replaces_entry_ids is None
                else replaces_entry_ids
            )
            entry = CompactionEntry(
                parent_id=self._parent_id,
                summary=summary,
                replaces_entry_ids=replaced,
            )
            await self._append_unlocked(entry)
            entries = await self.storage.read_all()
            state = SessionState.from_entries(entries)
            self._context_entry_ids = list(state.context_entry_ids)
            return entry

    async def context_entry_ids(self) -> tuple[str, ...]:
        async with self._lock:
            await self._initialize_unlocked()
            return tuple(self._context_entry_ids)

    async def _initialize_unlocked(self) -> None:
        """恢复已有文件写入位置；不存在的文件视为全新会话（不落盘）。"""
        if self._initialized:
            return
        self._initialized = True

        entries = await self.storage.read_all()
        if not entries:
            # 新会话：文件尚未创建，初始元数据推迟到首条消息落盘时写入。
            return

        state = SessionState.from_entries(entries)
        self._parent_id = entries[-1].id
        self._context_entry_ids = list(state.context_entry_ids)
        if state.model is not None:
            self.model = state.model
        else:
            await self._append_unlocked(
                ModelChangeEntry(parent_id=self._parent_id, model=self.model)
            )
        if any(entry.type == "thinking_level_change" for entry in entries):
            self.thinking_level = state.thinking_level
        else:
            await self._append_unlocked(
                ThinkingLevelChangeEntry(
                    parent_id=self._parent_id,
                    thinking_level=self.thinking_level,
                )
            )

    async def _ensure_initial_entries_unlocked(self) -> None:
        """首条消息落盘前补齐新会话的初始元数据三行（仅全新会话）。"""
        if self._parent_id is not None:
            # 已有历史：初始元数据早已写入，只追加消息。
            return
        await self._append_unlocked(SessionInfoEntry(cwd=str(self.cwd)))
        await self._append_unlocked(
            ModelChangeEntry(parent_id=self._parent_id, model=self.model)
        )
        await self._append_unlocked(
            ThinkingLevelChangeEntry(
                parent_id=self._parent_id,
                thinking_level=self.thinking_level,
            )
        )

    async def _append_unlocked(self, entry: SessionEntry) -> None:
        await self.storage.append(entry)
        self._parent_id = entry.id
