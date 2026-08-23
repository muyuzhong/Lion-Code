"""基于 canonical AgentMessage 的纯活跃上下文派生。"""

from __future__ import annotations

import posixpath
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import time
from typing import Protocol

from lion_code.context.estimator import estimate_messages_tokens
from lion_code.context.policy import ContextPolicy
from lion_code.context.projector import (
    budget_text,
    project_messages,
    replace_tool_result_text,
)
from lion_code.context.types import (
    ContextAction,
    ContextRuntimeState,
    ContextView,
    PreparedContext,
)
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

IsSnippableTool = Callable[[str], bool]


class _ContextLayer(Protocol):
    """Composition 注入 Kernel context 的结构化回调边界。"""

    @property
    def layer_id(self) -> str: ...

    def render(self, view: ContextView) -> str: ...


ContextLayerCallback = Callable[[], Sequence[_ContextLayer]]


@dataclass(frozen=True, slots=True)
class _ToolResultRef:
    message: ToolResultMessage
    call: ToolCall | None
    read_file_key: str | None


class ContextManager:
    """派生 Provider 上下文，不修改 Harness 或 Session 消息。"""

    def __init__(
        self,
        policy: ContextPolicy | None = None,
        *,
        is_snippable_tool: IsSnippableTool | None = None,
        context_layers: ContextLayerCallback | None = None,
    ) -> None:
        self.policy = policy or ContextPolicy()
        self._is_snippable_tool = is_snippable_tool or (lambda _name: False)
        self._context_layers = context_layers or (lambda: ())

    def prepare(
        self,
        messages: list[AgentMessage],
        state: ContextRuntimeState,
    ) -> PreparedContext:
        projected = project_messages(messages)
        actions: list[ContextAction] = []

        if state.utilization >= self.policy.budget_start_ratio:
            self._budget_tool_results(projected, state, actions)
        if self._should_snip(state):
            self._snip_stale_results(projected, actions)
        if self._cache_is_cold(state):
            self._clear_old_results(projected, actions)

        compaction_required = self.should_compact(state)
        if compaction_required:
            actions.append(ContextAction(type="request_compaction"))

        self._append_context_layers(
            projected,
            source_messages=messages,
            state=state,
            compaction_required=compaction_required,
        )

        prepared_messages = tuple(projected)

        return PreparedContext(
            messages=prepared_messages,
            actions=tuple(actions),
            estimated_tokens=estimate_messages_tokens(prepared_messages),
            compaction_required=compaction_required,
        )

    def _append_context_layers(
        self,
        projected: list[AgentMessage],
        *,
        source_messages: list[AgentMessage],
        state: ContextRuntimeState,
        compaction_required: bool,
    ) -> None:
        layers = tuple(self._context_layers())
        if not layers:
            return

        view = ContextView.from_messages(
            source_messages,
            state=state,
            compaction_required=compaction_required,
        )
        fragments = [(layer.layer_id, layer.render(view)) for layer in layers]
        rendered = [
            fragment.strip()
            for _layer_id, fragment in sorted(fragments, key=lambda item: item[0])
            if fragment.strip()
        ]
        if not rendered:
            return
        projected.append(
            UserMessage(
                content="<agent-state>\n" + "\n\n".join(rendered) + "\n</agent-state>"
            )
        )

    def should_compact(self, state: ContextRuntimeState) -> bool:
        return state.utilization >= self.policy.auto_compact_ratio

    def _budget_tool_results(
        self,
        messages: list[AgentMessage],
        state: ContextRuntimeState,
        actions: list[ContextAction],
    ) -> None:
        budget = (
            self.policy.aggressive_result_budget_chars
            if state.utilization >= self.policy.aggressive_budget_ratio
            else self.policy.normal_result_budget_chars
        )
        for ref in self._eligible_results(messages):
            original = ref.message.text
            if len(original) <= budget or self._is_placeholder(original):
                continue
            retained = budget_text(original, budget)
            replace_tool_result_text(ref.message, retained)
            actions.append(
                ContextAction(
                    type="budget_tool_result",
                    tool_call_id=ref.message.tool_call_id,
                    original_chars=len(original),
                    retained_chars=len(retained),
                )
            )

    def _snip_stale_results(
        self,
        messages: list[AgentMessage],
        actions: list[ContextAction],
    ) -> None:
        results = self._eligible_results(messages)
        protected = self._protected_result_indexes(results)
        for index, ref in enumerate(results):
            original = ref.message.text
            if index in protected or self._is_placeholder(original):
                continue
            replace_tool_result_text(ref.message, self.policy.snip_placeholder)
            actions.append(
                ContextAction(
                    type="snip_tool_result",
                    tool_call_id=ref.message.tool_call_id,
                    original_chars=len(original),
                    retained_chars=len(self.policy.snip_placeholder),
                )
            )

    def _clear_old_results(
        self,
        messages: list[AgentMessage],
        actions: list[ContextAction],
    ) -> None:
        results = self._eligible_results(messages)
        protected = self._protected_result_indexes(results)
        for index, ref in enumerate(results):
            original = ref.message.text
            if index in protected or self._is_placeholder(original):
                continue
            replace_tool_result_text(ref.message, self.policy.cleared_placeholder)
            actions.append(
                ContextAction(
                    type="clear_tool_result",
                    tool_call_id=ref.message.tool_call_id,
                    original_chars=len(original),
                    retained_chars=len(self.policy.cleared_placeholder),
                )
            )

    def _eligible_results(self, messages: list[AgentMessage]) -> list[_ToolResultRef]:
        calls: dict[str, ToolCall] = {}
        for message in messages:
            if isinstance(message, AssistantMessage):
                calls.update((call.id, call) for call in message.tool_calls)

        results: list[_ToolResultRef] = []
        for message in messages:
            if not isinstance(message, ToolResultMessage) or message.is_error:
                continue
            if not self._result_is_snippable(message):
                continue
            call = calls.get(message.tool_call_id)
            results.append(
                _ToolResultRef(
                    message=message,
                    call=call,
                    read_file_key=_read_file_key(message, call),
                )
            )
        return results

    def _result_is_snippable(self, message: ToolResultMessage) -> bool:
        details = message.details
        if isinstance(details, dict) and details.get("result_policy") == "snippable":
            return True
        return self._is_snippable_tool(message.tool_name)

    def _protected_result_indexes(self, results: list[_ToolResultRef]) -> set[int]:
        recent_start = max(0, len(results) - self.policy.keep_recent_results)
        protected = set(range(recent_start, len(results)))
        latest_read_by_file: dict[str, int] = {}
        for index, result in enumerate(results):
            if result.read_file_key is not None:
                latest_read_by_file[result.read_file_key] = index
        protected.update(latest_read_by_file.values())
        return protected

    def _should_snip(self, state: ContextRuntimeState) -> bool:
        if state.utilization < self.policy.snip_start_ratio:
            return False
        return not (
            self._cache_is_hot(state)
            and state.utilization < self.policy.hot_cache_override_ratio
        )

    def _cache_is_hot(self, state: ContextRuntimeState) -> bool:
        if state.last_model_call_at is None:
            return False
        now = state.now if state.now is not None else time()
        return now - state.last_model_call_at < self.policy.cache_idle_seconds

    def _cache_is_cold(self, state: ContextRuntimeState) -> bool:
        if state.last_model_call_at is None:
            return False
        return not self._cache_is_hot(state)

    def _is_placeholder(self, text: str) -> bool:
        return text in {
            self.policy.snip_placeholder,
            self.policy.cleared_placeholder,
        }


def _read_file_key(message: ToolResultMessage, call: ToolCall | None) -> str | None:
    if message.tool_name != "read_file" or call is None:
        return None
    raw_path = call.arguments.get("file_path") or call.arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    return posixpath.normpath(raw_path.replace("\\", "/")).casefold()
