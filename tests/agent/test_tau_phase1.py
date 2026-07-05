from nanoagent.agent import (
    AgentStartEvent,
    AssistantMessage,
    JSONObject,
    JSONPrimitive,
    JSONValue,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def test_agent_layer_exposes_tau_style_json_aliases():
    primitive: JSONPrimitive = "text"
    value: JSONValue = {"items": [primitive, 1, True, None]}
    obj: JSONObject = {"value": value}

    assert obj["value"] == {"items": ["text", 1, True, None]}


def test_agent_layer_uses_tau_style_transcript_models():
    tool_call = ToolCall(id="call_1", name="echo", arguments={"text": "hi"})
    assistant = AssistantMessage(content="use tool", tool_calls=[tool_call])
    tool_result = ToolResultMessage(
        tool_call_id="call_1",
        name="echo",
        content="hi",
        data={"echo": "hi"},
    )

    assert UserMessage(content="go").role == "user"
    assert assistant.role == "assistant"
    assert assistant.tool_calls[0].arguments == {"text": "hi"}
    assert tool_result.role == "tool"
    assert tool_result.ok is True


def test_agent_layer_uses_tau_style_events():
    event = AgentStartEvent()

    assert event.type == "agent_start"
