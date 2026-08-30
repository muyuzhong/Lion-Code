"""In-memory session state reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from lion_code.core.messages import AgentMessage, UserMessage
from lion_code.core.session.entries import (
    CompactionEntry,
    SessionEntry,
    SessionInfoEntry,
)


@dataclass(frozen=True, slots=True)
class SessionState:
    """Current session state derived from append-only entries."""

    messages: tuple[AgentMessage, ...]
    model: str | None
    thinking_level: str | None
    label: str | None
    session_info: SessionInfoEntry | None
    compaction_entries: tuple[CompactionEntry, ...]
    context_entry_ids: tuple[str, ...]
    entries: tuple[SessionEntry, ...]

    @classmethod
    def from_entries(cls, entries: list[SessionEntry]) -> SessionState:
        """Replay entries in storage order into session state."""
        replay_entries = entries

        message_rows: list[tuple[str, AgentMessage]] = []
        model: str | None = None
        thinking_level: str | None = None
        label: str | None = None
        session_info: SessionInfoEntry | None = None
        compaction_entries: list[CompactionEntry] = []

        for entry in replay_entries:
            match entry.type:
                case "message":
                    message_rows.append((entry.id, entry.message))
                case "model_change":
                    model = entry.model
                case "thinking_level_change":
                    thinking_level = entry.thinking_level
                case "label":
                    label = entry.label
                case "session_info":
                    session_info = entry
                case "compaction":
                    compaction_entries.append(entry)
                    message_rows = _apply_compaction(message_rows, entry)
        return cls(
            messages=tuple(message for _entry_id, message in message_rows),
            model=model,
            thinking_level=thinking_level,
            label=label,
            session_info=session_info,
            compaction_entries=tuple(compaction_entries),
            context_entry_ids=tuple(entry_id for entry_id, _message in message_rows),
            entries=tuple(replay_entries),
        )


def _apply_compaction(
    message_rows: list[tuple[str, AgentMessage]],
    entry: CompactionEntry,
) -> list[tuple[str, AgentMessage]]:
    replaced_ids = set(entry.replaces_entry_ids)
    retained: list[tuple[str, AgentMessage]] = []
    inserted_summary = False
    for entry_id, message in message_rows:
        if entry_id not in replaced_ids:
            retained.append((entry_id, message))
            continue
        if not inserted_summary:
            retained.append(
                (
                    entry.id,
                    UserMessage(
                        content=_format_compaction_summary(entry.summary),
                        timestamp=int(entry.timestamp * 1000),
                    ),
                )
            )
            inserted_summary = True

    if not inserted_summary:
        retained.append(
            (
                entry.id,
                UserMessage(
                    content=_format_compaction_summary(entry.summary),
                    timestamp=int(entry.timestamp * 1000),
                ),
            )
        )
    return retained


def _format_compaction_summary(summary: str) -> str:
    return f"Previous conversation summary:\n{summary}"
