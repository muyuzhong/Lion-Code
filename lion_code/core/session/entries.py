"""Append-only session entry models."""

from __future__ import annotations

from time import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from lion_code.core.messages import AgentMessage


def new_entry_id() -> str:
    """Return a unique session entry id."""
    return uuid4().hex


def current_timestamp() -> float:
    """Return the current Unix timestamp."""
    return time()


class BaseSessionEntry(BaseModel):
    """Common fields shared by all append-only session entries."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_entry_id)
    parent_id: str | None = None
    timestamp: float = Field(default_factory=current_timestamp)


class MessageEntry(BaseSessionEntry):
    """A transcript message entry."""

    type: Literal["message"] = "message"
    message: AgentMessage


class ModelChangeEntry(BaseSessionEntry):
    """A model selection change entry."""

    type: Literal["model_change"] = "model_change"
    model: str


class ThinkingLevelChangeEntry(BaseSessionEntry):
    """A thinking/reasoning level change entry."""

    type: Literal["thinking_level_change"] = "thinking_level_change"
    thinking_level: str | None = None


class CompactionEntry(BaseSessionEntry):
    """A context summary that replaces older message entries during replay."""

    type: Literal["compaction"] = "compaction"
    summary: str
    replaces_entry_ids: list[str] = Field(default_factory=list)


class LabelEntry(BaseSessionEntry):
    """A human-readable session label entry."""

    type: Literal["label"] = "label"
    label: str


class SessionInfoEntry(BaseSessionEntry):
    """Basic session metadata entry."""

    type: Literal["session_info"] = "session_info"
    created_at: float = Field(default_factory=current_timestamp)
    cwd: str | None = None
    title: str | None = None


type SessionEntry = Annotated[
    MessageEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | CompactionEntry
    | LabelEntry
    | SessionInfoEntry,
    Field(discriminator="type"),
]
