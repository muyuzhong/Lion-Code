"""把活跃 Memory 非破坏性地注入 canonical Provider 投影。"""

from __future__ import annotations

from collections.abc import Sequence

from lion_code.context import estimate_messages_tokens, project_messages
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from lion_code.memory_runtime.types import (
    MemoryContextPolicy,
    MemoryInjectionReport,
    MemoryOverlay,
)

_SOURCE_PRIORITY = {"project": 0, "session": 1, "auto": 2}


class MemoryContextInjector:
    """在不修改输入消息的前提下派生带 Memory 的临时投影。"""

    def __init__(self, policy: MemoryContextPolicy | None = None) -> None:
        self.policy = policy or MemoryContextPolicy()

    def inject(
        self,
        messages: tuple[AgentMessage, ...],
        overlays: Sequence[MemoryOverlay],
        *,
        max_tokens: int | None = None,
    ) -> tuple[list[AgentMessage], MemoryInjectionReport]:
        projected = project_messages(messages)
        if not overlays:
            return projected, MemoryInjectionReport()

        if _has_unresolved_tool_calls(projected):
            return projected, MemoryInjectionReport(
                skipped_paths=tuple(item.path for item in overlays)
            )

        selected: list[MemoryOverlay] = []
        skipped: list[str] = []
        selected_bytes = 0
        auto_bytes = 0
        auto_count = 0
        seen_paths: set[str] = set()
        ordered = sorted(
            enumerate(overlays),
            key=lambda pair: (_SOURCE_PRIORITY[pair[1].source], pair[0]),
        )
        for _, overlay in ordered:
            if overlay.path in seen_paths:
                skipped.append(overlay.path)
                continue
            seen_paths.add(overlay.path)
            if overlay.required or overlay.source in {"project", "session"}:
                selected.append(overlay)
                selected_bytes += overlay.byte_size
                continue
            if (
                auto_count >= self.policy.max_active_memories
                or auto_bytes + overlay.byte_size > self.policy.max_injection_bytes
            ):
                skipped.append(overlay.path)
                continue

            candidate = [*selected, overlay]
            if (
                max_tokens is not None
                and estimate_messages_tokens(self._apply(projected, candidate))
                > max_tokens
            ):
                skipped.append(overlay.path)
                continue
            selected.append(overlay)
            selected_bytes += overlay.byte_size
            auto_bytes += overlay.byte_size
            auto_count += 1

        return self._apply(projected, selected), MemoryInjectionReport(
            injected_paths=tuple(item.path for item in selected),
            injected_bytes=selected_bytes,
            skipped_paths=tuple(skipped),
        )

    def _apply(
        self,
        messages: list[AgentMessage],
        overlays: Sequence[MemoryOverlay],
    ) -> list[AgentMessage]:
        if not overlays:
            return list(messages)
        projected = list(messages)
        block = self._format(overlays)
        if projected and isinstance(projected[-1], UserMessage):
            projected[-1] = self._append_to_user(projected[-1], block)
        else:
            projected.append(UserMessage(content=block))
        return projected

    @staticmethod
    def _format(overlays: Sequence[MemoryOverlay]) -> str:
        rows = ["<relevant-memory>"]
        for source in ("project", "session", "auto"):
            items = [item for item in overlays if item.source == source]
            if not items:
                continue
            rows.extend(
                [
                    f"<{source}-memory>",
                    *(f"## {item.path}\n{item.content}" for item in items),
                    f"</{source}-memory>",
                ]
            )
        rows.append("</relevant-memory>")
        return "\n\n".join(rows)

    @staticmethod
    def _append_to_user(message: UserMessage, text: str) -> UserMessage:
        if isinstance(message.content, str):
            content = f"{message.content}\n\n{text}" if message.content else text
        else:
            content = [*message.content, TextContent(text=text)]
        return message.model_copy(update={"content": content})


def _has_unresolved_tool_calls(messages: Sequence[AgentMessage]) -> bool:
    pending: set[str] = set()
    for message in messages:
        if isinstance(message, AssistantMessage):
            pending.update(call.id for call in message.tool_calls)
        elif isinstance(message, ToolResultMessage):
            pending.discard(message.tool_call_id)
    return bool(pending)
