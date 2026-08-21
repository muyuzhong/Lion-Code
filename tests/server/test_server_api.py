"""Server REST 与 WebSocket 接口的单元测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lion_code.application.session import LionCodingSession
from lion_code.core.events import (
    AgentEndEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
)
from lion_code.core.messages import AssistantMessage, TextContent
from lion_code.core.provider_events import TextDeltaEvent
from lion_code.server.app import create_app
from lion_code.server.bridge import SessionWebsocketBridge

try:
    from application.fakes import FakeCodingSessionBackend
except ModuleNotFoundError:
    from tests.application.fakes import FakeCodingSessionBackend


class MockWebSocket:
    """用于单元测试的模拟 WebSocket。"""

    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.closed: bool = False

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def close(self) -> None:
        self.closed = True


def _build_test_session() -> tuple[LionCodingSession, FakeCodingSessionBackend]:
    backend = FakeCodingSessionBackend(
        cwd=Path("/workspace"),
        model="gpt-4o",
        provider_name="openai",
        sessions=[
            {
                "id": "sess-1",
                "startTime": "2026-08-21T10:00:00",
                "messageCount": 4,
                "cwd": str(Path("/workspace")),
            },
            {
                "id": "sess-2",
                "startTime": "2026-08-21T11:00:00",
                "messageCount": 2,
                "cwd": str(Path("/other")),
            },
        ],
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    return session, backend


def test_health_check() -> None:
    session, _ = _build_test_session()
    app = create_app(session)
    client = TestClient(app)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_status() -> None:
    session, _ = _build_test_session()
    app = create_app(session)
    client = TestClient(app)

    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "gpt-4o"
    assert data["provider_name"] == "openai"
    assert data["api_configured"] is True
    assert "available_thinking_levels" in data


def test_list_and_resume_sessions() -> None:
    session, backend = _build_test_session()
    app = create_app(session)
    client = TestClient(app)

    # 只能列出当前 workspace 下的会话
    res = client.get("/api/sessions")
    assert res.status_code == 200
    sessions = res.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"

    # 恢复会话
    res_resume = client.post("/api/sessions/resume", json={"session_id": "sess-1"})
    assert res_resume.status_code == 200
    assert res_resume.json()["success"] is True
    assert ("resume", "sess-1") in backend.session_operations

    # 新建会话
    res_new = client.post("/api/sessions/new")
    assert res_new.status_code == 200
    assert ("new", None) in backend.session_operations


def test_configure_provider_and_thinking() -> None:
    session, backend = _build_test_session()
    app = create_app(session)
    client = TestClient(app)

    # 切换 thinking
    res_think = client.post("/api/thinking", json={"level": "high"})
    assert res_think.status_code == 200
    assert res_think.json()["thinking_level"] == "high"

    # 配置模型
    res_cfg = client.post(
        "/api/config/provider",
        json={
            "model": "claude-3-5-sonnet",
            "api_key": "sk-test",
            "provider": "anthropic",
        },
    )
    assert res_cfg.status_code == 200
    assert len(backend.provider_configure_calls) == 1


def test_websocket_chat_streaming() -> None:
    session, backend = _build_test_session()
    msg = AssistantMessage(content=(TextContent(text="Hello, World!"),))
    backend.prompt_scripts.append(
        [
            AgentStartEvent(),
            MessageStartEvent(message=msg),
            MessageUpdateEvent(
                message=msg,
                assistant_message_event=TextDeltaEvent(
                    content_index=0, delta="Hello, ", partial=msg
                ),
            ),
            MessageUpdateEvent(
                message=msg,
                assistant_message_event=TextDeltaEvent(
                    content_index=0, delta="World!", partial=msg
                ),
            ),
            MessageEndEvent(
                message=AssistantMessage(
                    content=(TextContent(text="Hello, World!"),),
                    stop_reason="stop",
                )
            ),
            AgentEndEvent(),
        ]
    )

    app = create_app(session)
    client = TestClient(app)

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"action": "prompt", "prompt": "Hi"})

        received_events: list[dict[str, Any]] = []
        while True:
            raw = ws.receive_text()
            event = json.loads(raw)
            received_events.append(event)
            if event.get("type") == "agent_settled":
                break

        types = [e.get("type") for e in received_events]
        assert "agent_start" in types
        assert "message_update" in types
        assert "message_end" in types
        assert "session_agent_end" in types
        assert "agent_settled" in types


async def test_websocket_confirm_approval_flow() -> None:
    session, backend = _build_test_session()
    ws = MockWebSocket()
    bridge = SessionWebsocketBridge(session, ws)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    # 1. 触发 confirm 回调
    assert backend.confirm_fn is not None
    confirm_task = asyncio.create_task(backend.confirm_fn("Do you want to run rm -rf /?"))
    await asyncio.sleep(0.01)

    # 2. 检查 WebSocket 收到 confirm_request
    assert len(ws.sent_texts) == 1
    data = json.loads(ws.sent_texts[0])
    assert data.get("type") == "confirm_request"
    req_id = data.get("request_id")
    assert "rm -rf" in data.get("message", "")

    # 3. 模拟前端回复 confirm_response
    await bridge.handle_inbound_data(
        {"action": "confirm_response", "request_id": req_id, "approved": True}
    )

    # 4. 验证 confirm_fn 返回 True
    result = await confirm_task
    assert result is True

    bridge.unbind_callbacks()


async def test_websocket_plan_approval_flow() -> None:
    session, backend = _build_test_session()
    ws = MockWebSocket()
    bridge = SessionWebsocketBridge(session, ws)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    assert backend.plan_approval_fn is not None
    plan_task = asyncio.create_task(backend.plan_approval_fn("1. Step A\n2. Step B"))
    await asyncio.sleep(0.01)

    assert len(ws.sent_texts) == 1
    data = json.loads(ws.sent_texts[0])
    assert data.get("type") == "plan_approval_request"
    req_id = data.get("request_id")
    assert "Step A" in data.get("plan", "")

    # 前端选择 execute
    await bridge.handle_inbound_data(
        {
            "action": "plan_approval_response",
            "request_id": req_id,
            "choice": "execute",
            "feedback": None,
        }
    )

    result = await plan_task
    assert result == {"choice": "execute", "feedback": None}

    bridge.unbind_callbacks()
