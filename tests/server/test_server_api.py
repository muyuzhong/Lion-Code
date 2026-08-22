"""Server REST 与 WebSocket 接口的单元测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
from lion_code.server.app import create_app, run_server
from lion_code.server.bridge import SessionWebsocketBridge

try:
    from application.fakes import FakeCodingSessionBackend
except ModuleNotFoundError:
    from tests.application.fakes import FakeCodingSessionBackend

_CAPABILITY = "A" * 43
_WRONG_CAPABILITY = "B" * 43
_APP_ORIGIN = "http://127.0.0.1:8000"
_VITE_ORIGIN = "http://127.0.0.1:3000"
_WS_URL = "ws://127.0.0.1:8000/ws/chat"


def _authorization_headers(capability: str = _CAPABILITY) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {capability}",
        "Origin": _APP_ORIGIN,
    }


def _websocket_protocols(capability: str = _CAPABILITY) -> list[str]:
    return ["lion-code", f"lion-code-capability.{capability}"]


def _build_client(
    session: LionCodingSession,
    *,
    authorized: bool = True,
) -> TestClient:
    headers = _authorization_headers() if authorized else None
    return TestClient(
        create_app(session, capability=_CAPABILITY),
        base_url=_APP_ORIGIN,
        headers=headers,
    )


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
    client = _build_client(session, authorized=False)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_api_documentation_is_not_public() -> None:
    session, _ = _build_test_session()
    app = create_app(session, capability=_CAPABILITY)

    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert route_paths.isdisjoint({"/docs", "/redoc", "/openapi.json"})


def test_get_status() -> None:
    session, _ = _build_test_session()
    client = _build_client(session)

    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "gpt-4o"
    assert data["provider_name"] == "openai"
    assert data["api_configured"] is True
    assert "available_thinking_levels" in data


def test_list_and_resume_sessions() -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

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


def test_get_messages() -> None:
    session, backend = _build_test_session()
    user_msg = AssistantMessage(content=(TextContent(text="Hello!"),))
    backend.messages = (user_msg,)
    client = _build_client(session)

    res = client.get("/api/messages")
    assert res.status_code == 200
    msgs = res.json()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "Hello!"


def test_configure_provider_and_thinking() -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    # 切换 thinking
    res_think = client.post("/api/thinking", json={"level": "high"})
    assert res_think.status_code == 200
    assert res_think.json()["thinking_level"] == "high"

    # 配置模型
    with patch("lion_code.server.app.save_api_config") as save_config:
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
    save_config.assert_called_once()


def test_protected_rest_requires_exact_local_access() -> None:
    session, _ = _build_test_session()
    client = _build_client(session, authorized=False)

    missing = client.get("/api/status")
    wrong = client.get(
        "/api/status",
        headers=_authorization_headers(_WRONG_CAPABILITY),
    )
    foreign_origin = client.get(
        "/api/status",
        headers={
            "Authorization": f"Bearer {_CAPABILITY}",
            "Origin": "https://evil.example",
        },
    )
    foreign_host = client.get(
        "/api/status",
        headers={
            "Authorization": f"Bearer {_CAPABILITY}",
            "Host": "evil.example",
        },
    )
    vite_origin = client.get(
        "/api/status",
        headers={
            "Authorization": f"Bearer {_CAPABILITY}",
            "Origin": _VITE_ORIGIN,
        },
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert foreign_origin.status_code == 403
    assert foreign_host.status_code == 403
    assert vite_origin.status_code == 200
    for response in (missing, wrong, foreign_origin, foreign_host):
        assert _CAPABILITY not in response.text
        assert _WRONG_CAPABILITY not in response.text


def test_cors_allows_only_exact_loopback_origins() -> None:
    session, _ = _build_test_session()
    client = _build_client(session, authorized=False)
    preflight_headers = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization",
    }

    allowed = client.options(
        "/api/status",
        headers={"Origin": _VITE_ORIGIN, **preflight_headers},
    )
    denied = client.options(
        "/api/status",
        headers={"Origin": "https://evil.example", **preflight_headers},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == _VITE_ORIGIN
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize("origin", [_APP_ORIGIN, _VITE_ORIGIN])
def test_websocket_chat_streaming(origin: str) -> None:
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

    client = _build_client(session)

    with client.websocket_connect(
        _WS_URL,
        subprotocols=_websocket_protocols(),
        headers={"Origin": origin},
    ) as ws:
        assert ws.accepted_subprotocol == "lion-code"
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


@pytest.mark.parametrize(
    ("protocols", "headers"),
    [
        ([], {"Origin": _APP_ORIGIN}),
        (_websocket_protocols(_WRONG_CAPABILITY), {"Origin": _APP_ORIGIN}),
        (_websocket_protocols(), {}),
        (_websocket_protocols(), {"Origin": "https://evil.example"}),
        (
            _websocket_protocols(),
            {"Origin": _APP_ORIGIN, "Host": "evil.example"},
        ),
    ],
)
def test_websocket_rejects_untrusted_handshakes(
    protocols: list[str],
    headers: dict[str, str],
) -> None:
    session, _ = _build_test_session()
    client = _build_client(session, authorized=False)

    with pytest.raises(WebSocketDisconnect) as denial:
        with client.websocket_connect(
            _WS_URL,
            subprotocols=protocols,
            headers=headers,
        ):
            pass

    assert denial.value.code == 1008
    assert _CAPABILITY not in str(denial.value)
    assert _WRONG_CAPABILITY not in str(denial.value)


def test_run_server_uses_loopback_and_fragment_capability(monkeypatch) -> None:
    test_session, _ = _build_test_session()
    opened_urls: list[str] = []
    app_calls: list[tuple[str, int]] = []
    server_calls: list[dict[str, Any]] = []

    class ImmediateThread:
        def __init__(self, *, target, daemon: bool) -> None:
            assert daemon is True
            self._target = target

        def start(self) -> None:
            self._target()

    def fake_create_app(
        session: LionCodingSession,
        *,
        capability: str,
        port: int,
    ) -> object:
        assert session is test_session
        app_calls.append((capability, port))
        return object()

    monkeypatch.setattr(
        "lion_code.server.app._generate_capability", lambda: _CAPABILITY
    )
    monkeypatch.setattr("lion_code.server.app.create_app", fake_create_app)
    monkeypatch.setattr("lion_code.server.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("lion_code.server.app.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("lion_code.server.app.webbrowser.open", opened_urls.append)
    monkeypatch.setattr(
        "uvicorn.run",
        lambda _app, **kwargs: server_calls.append(kwargs),
    )

    run_server(test_session, port=8123, open_browser=True)

    assert app_calls == [(_CAPABILITY, 8123)]
    assert server_calls == [{"host": "127.0.0.1", "port": 8123, "log_level": "info"}]
    assert opened_urls == [f"http://127.0.0.1:8123/#capability={_CAPABILITY}"]
    assert "?" not in opened_urls[0]


def test_run_server_headless_does_not_deliver_capability(monkeypatch) -> None:
    test_session, _ = _build_test_session()
    opened_urls: list[str] = []
    thread_targets: list[object] = []
    server_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "lion_code.server.app._generate_capability", lambda: _CAPABILITY
    )
    monkeypatch.setattr(
        "lion_code.server.app.create_app",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "lion_code.server.app._browser_url",
        lambda *_args: pytest.fail("headless 启动不应构造 capability URL"),
    )
    monkeypatch.setattr(
        "lion_code.server.app.threading.Thread",
        lambda **kwargs: thread_targets.append(kwargs),
    )
    monkeypatch.setattr("lion_code.server.app.webbrowser.open", opened_urls.append)
    monkeypatch.setattr(
        "uvicorn.run",
        lambda _app, **kwargs: server_calls.append(kwargs),
    )

    run_server(test_session, port=8123, open_browser=False)

    assert opened_urls == []
    assert thread_targets == []
    assert server_calls == [{"host": "127.0.0.1", "port": 8123, "log_level": "info"}]


async def test_websocket_confirm_approval_flow() -> None:
    session, backend = _build_test_session()
    ws = MockWebSocket()
    bridge = SessionWebsocketBridge(session, ws)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    # 1. 触发 confirm 回调
    assert backend.confirm_fn is not None
    confirm_task = asyncio.create_task(
        backend.confirm_fn("Do you want to run rm -rf /?")
    )
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
