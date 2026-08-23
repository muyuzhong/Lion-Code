"""QueryContextLayer SPI 测试：ContextManager 对 query 投影层的通用契约。

验收（PR4 R1/R2）：
1. ContextManager 从当前 prepared messages 取最新 user query 传给层；
2. 输出与 ContextLayer 一起按 layer_id 排序合并进同一条临时
   <agent-state> 消息，空片段被丢弃；
3. 渲染结果不进入 canonical history、JSONL 或 compactor 输入；
4. 同一 tool loop 内 query 稳定，新 user turn 刷新。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lion_code.context import (
    SUMMARY_HEADINGS,
    ContextManager,
    ContextRuntimeState,
    ContextView,
    ProviderContextCompactor,
    build_compaction_request,
)
from lion_code.context.projector import project_messages
from lion_code.core import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.core.session import JsonlSessionStorage
from lion_code.session_runtime import SessionRecorder


class _StateLayer:
    def __init__(self, layer_id: str, fragment: str) -> None:
        self.layer_id = layer_id
        self.fragment = fragment
        self.views: list[ContextView] = []

    def render(self, view: ContextView) -> str:
        self.views.append(view)
        return self.fragment


class _QueryLayer:
    def __init__(self, layer_id: str, fragment: str = "") -> None:
        self.layer_id = layer_id
        self.fragment = fragment
        self.queries: list[str] = []
        self.views: list[ContextView] = []

    def render(self, query: str, view: ContextView) -> str:
        self.queries.append(query)
        self.views.append(view)
        return self.fragment


def _state() -> ContextRuntimeState:
    return ContextRuntimeState(effective_window_tokens=1_000, last_prompt_tokens=100)


def test_query_layer_receives_latest_user_query_and_view() -> None:
    layer = _QueryLayer("memory", "M")
    source = [
        UserMessage(content="first question"),
        AssistantMessage(
            content=[ToolCall(id="call-1", name="read_file", arguments={})],
            stop_reason="toolUse",
        ),
        ToolResultMessage(
            tool_call_id="call-1",
            tool_name="read_file",
            content=[TextContent(text="ok")],
        ),
        UserMessage(content="latest question about db paths"),
    ]

    prepared = ContextManager(
        query_context_layers=lambda: (layer,),
    ).prepare(source, _state())

    assert layer.queries == ["latest question about db paths"]
    assert len(layer.views) == 1
    assert isinstance(layer.views[0], ContextView)
    assert prepared.messages[-1].text == ("<agent-state>\nM\n</agent-state>")


def test_query_layer_without_user_message_renders_with_empty_query() -> None:
    layer = _QueryLayer("memory", "M")
    source = [AssistantMessage(content=[TextContent(text="hi")], stop_reason="stop")]

    ContextManager(query_context_layers=lambda: (layer,)).prepare(source, _state())

    assert layer.queries == [""]


def test_query_and_state_layers_merge_into_one_sorted_message() -> None:
    state_layer = _StateLayer("agent-state", "State")
    query_layer = _QueryLayer("memory", "Memory block")
    source = [UserMessage(content="q")]

    prepared = ContextManager(
        context_layers=lambda: (state_layer,),
        query_context_layers=lambda: (query_layer,),
    ).prepare(source, _state())

    assert len(prepared.messages) == len(source) + 1
    tail = prepared.messages[-1]
    assert isinstance(tail, UserMessage)
    # layer_id 排序：agent-state < memory；同一条临时消息承载两类投影
    assert tail.text == "<agent-state>\nState\n\nMemory block\n</agent-state>"
    assert all(message is not tail for message in source)
    # 排序只认 layer_id：query 层 id 更小时排在前
    early_query = _QueryLayer("a-query", "A")
    late_state = _StateLayer("z-state", "Z")
    merged = ContextManager(
        context_layers=lambda: (late_state,),
        query_context_layers=lambda: (early_query,),
    ).prepare([UserMessage(content="q")], _state())
    assert merged.messages[-1].text == "<agent-state>\nA\n\nZ\n</agent-state>"


def test_blank_query_fragment_is_dropped_and_no_message_appended() -> None:
    layer = _QueryLayer("memory", "   ")
    source = [UserMessage(content="q")]

    prepared = ContextManager(query_context_layers=lambda: (layer,)).prepare(
        source, _state()
    )

    assert [message.model_dump(mode="json") for message in prepared.messages] == [
        message.model_dump(mode="json") for message in project_messages(source)
    ]
    assert not any("<agent-state>" in message.text for message in prepared.messages)


def test_no_query_layers_default_keeps_projection_unchanged() -> None:
    source = [UserMessage(content="keep")]
    state = _state()
    expected = tuple(project_messages(source))

    prepared = ContextManager().prepare(source, state)

    assert [message.model_dump(mode="json") for message in prepared.messages] == [
        message.model_dump(mode="json") for message in expected
    ]


def test_query_stable_within_tool_loop_and_refreshes_per_user_turn() -> None:
    layer = _QueryLayer("memory", "M")
    manager = ContextManager(query_context_layers=lambda: (layer,))
    source = [UserMessage(content="first question")]

    manager.prepare(source, _state())
    # 模拟 tool loop：追加 assistant/tool result 后再次 prepare，
    # 最新 user message 不变 → 同一 query（FTS 结果确定性）
    source.append(
        AssistantMessage(
            content=[ToolCall(id="call-1", name="read_file", arguments={})],
            stop_reason="toolUse",
        )
    )
    source.append(
        ToolResultMessage(
            tool_call_id="call-1",
            tool_name="read_file",
            content=[TextContent(text="ok")],
        )
    )
    manager.prepare(source, _state())
    assert layer.queries == ["first question", "first question"]

    # 新 user turn：query 刷新
    source.append(UserMessage(content="second question"))
    manager.prepare(source, _state())
    assert layer.queries[-1] == "second question"


@pytest.mark.asyncio
async def test_query_fragment_never_enters_history_jsonl_or_compactor_input(
    tmp_path: Path,
) -> None:
    layer = _QueryLayer("memory", "Secret memory fragment")
    source = [UserMessage(content="canonical question")]

    prepared = ContextManager(query_context_layers=lambda: (layer,)).prepare(
        source, _state()
    )
    fragment = prepared.messages[-1].text
    assert fragment.startswith("<agent-state>")
    assert all(message.text != fragment for message in source)

    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    recorder = SessionRecorder(
        session_id="session",
        model="model",
        thinking_level="disabled",
        cwd=tmp_path,
        storage=storage,
    )
    entry = await recorder.record_message(source[0])
    await recorder.record_compaction(
        summary="summary",
        replaces_entry_ids=[entry.id],
    )
    jsonl = (tmp_path / "session.jsonl").read_text(encoding="utf-8")
    assert "Secret memory fragment" not in jsonl

    class _RecordingProvider:
        def __init__(self) -> None:
            self.messages: list[list] = []

        def stream_response(self, **kwargs):
            self.messages.append(list(kwargs["messages"]))

            async def events():
                yield AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        content=[
                            TextContent(
                                text="\n\n".join(
                                    f"{heading}\ncontent"
                                    for heading in SUMMARY_HEADINGS
                                )
                            )
                        ]
                    ),
                )

            return events()

    provider = _RecordingProvider()
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "model")
    await compactor.summarize(
        build_compaction_request(
            history=tuple(source),
            recent_context=(),
            requested_objective=None,
            effective_window_tokens=2_000,
            input_ratio=0.85,
        )
    )
    assert all("Secret memory fragment" not in m.text for m in provider.messages[0])
