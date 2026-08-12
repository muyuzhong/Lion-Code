"""Conversation value objects shared by Core and its boundary adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """Queued user text exposed without leaking Harness message containers."""

    steering: tuple[str, ...] = ()
    follow_up: tuple[str, ...] = ()
