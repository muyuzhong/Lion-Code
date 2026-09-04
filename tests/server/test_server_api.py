"""Server REST 与 WebSocket 接口的单元测试。"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lion_code import config as lion_config
from lion_code.application.session import LionCodingSession
from lion_code.core.events import (
    AgentEndEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
)
from lion_code.core.messages import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from lion_code.core.provider_events import TextDeltaEvent
from lion_code.server import app as server_app_module
from lion_code.server.app import create_app
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


class BlockingMockWebSocket(MockWebSocket):
    """保持一次发送挂起，用于验证断线会回收 notice task。"""

    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.send_cancelled = False

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)
        self.send_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.send_cancelled = True
            raise


def _build_test_session() -> tuple[LionCodingSession, FakeCodingSessionBackend]:
    backend = FakeCodingSessionBackend(
        cwd=Path("/workspace"),
        model="gpt-4o",
        provider_name="openai",
        provider_config_data={
            "use_openai": True,
            "model": "gpt-4o",
            "api_key": "sk-old",
            "base_url": "https://api.test/v1",
        },
        sessions=[
            {
                "id": "sess-1",
                "label": "当前会话",
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
    assert data["provider_blocker_code"] is None
    assert "available_thinking_levels" in data


def test_get_status_reports_stable_provider_blocker_code() -> None:
    backend = FakeCodingSessionBackend(
        cwd=Path("/workspace"),
        api_configured=False,
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    client = _build_client(session)

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["api_configured"] is False
    assert (
        response.json()["provider_blocker_code"]
        == "provider_configuration_required"
    )


def test_get_provider_config_returns_explicit_snapshot_without_status_key() -> None:
    session, _ = _build_test_session()
    client = _build_client(session)

    response = client.get("/api/config/provider")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "sk-old",
        "base_url": "https://api.test/v1",
    }
    status = client.get("/api/status")
    assert "sk-old" not in status.text


def test_list_and_resume_sessions() -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    # 只能列出当前 workspace 下的会话
    res = client.get("/api/sessions")
    assert res.status_code == 200
    sessions = res.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"
    assert sessions[0]["label"] == "当前会话"

    res_rename = client.post(
        "/api/sessions/rename",
        json={"session_id": "sess-1", "label": "需求文档"},
    )
    assert res_rename.status_code == 200
    assert res_rename.json()["label"] == "需求文档"
    assert backend.sessions[0]["label"] == "需求文档"

    # 恢复会话
    res_resume = client.post("/api/sessions/resume", json={"session_id": "sess-1"})
    assert res_resume.status_code == 200
    assert res_resume.json()["success"] is True
    assert ("resume", "sess-1") in backend.session_operations

    # 新建会话
    res_new = client.post("/api/sessions/new")
    assert res_new.status_code == 200
    assert ("new", None) in backend.session_operations


def test_list_sessions_zero_match_returns_empty() -> None:
    backend = FakeCodingSessionBackend(
        cwd=Path("/workspace"),
        model="gpt-4o",
        provider_name="openai",
        sessions=[
            {
                "id": "sess-other",
                "startTime": "2026-08-21T10:00:00",
                "messageCount": 4,
                "cwd": str(Path("/other")),
            }
        ],
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    client = _build_client(session)

    res = client.get("/api/sessions")

    assert res.status_code == 200
    assert res.json() == []


def test_rename_session_rejects_blank_cross_workspace_and_running() -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    blank = client.post(
        "/api/sessions/rename",
        json={"session_id": "sess-1", "label": "   "},
    )
    foreign = client.post(
        "/api/sessions/rename",
        json={"session_id": "sess-2", "label": "其他项目"},
    )
    session._running = True
    running = client.post(
        "/api/sessions/rename",
        json={"session_id": "sess-1", "label": "运行中"},
    )

    assert blank.status_code == 422
    assert foreign.status_code == 404
    assert running.status_code == 400
    assert not any(operation[0] == "rename" for operation in backend.session_operations)


def test_list_and_resume_legacy_session_without_cwd() -> None:
    backend = FakeCodingSessionBackend(
        cwd=Path("/workspace"),
        model="gpt-4o",
        provider_name="openai",
        sessions=[
            {
                "id": "sess-legacy",
                "startTime": "2026-08-21T10:00:00",
                "messageCount": 4,
                "cwd": None,
            }
        ],
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    client = _build_client(session)

    listed = client.get("/api/sessions").json()
    assert [s["id"] for s in listed] == ["sess-legacy"]

    res_resume = client.post("/api/sessions/resume", json={"session_id": "sess-legacy"})
    assert res_resume.status_code == 200


def test_list_sessions_matches_case_insensitive_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 模拟 Windows 的 normcase（小写化）语义，保证测试在 Linux CI 上同样成立
    monkeypatch.setattr(os.path, "normcase", lambda s: s.lower())

    backend = FakeCodingSessionBackend(
        cwd=Path("/Workspace"),
        model="gpt-4o",
        provider_name="openai",
        sessions=[
            {
                "id": "sess-case",
                "startTime": "2026-08-21T10:00:00",
                "messageCount": 4,
                "cwd": str(Path("/WORKSPACE")),
            }
        ],
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    client = _build_client(session)

    res = client.get("/api/sessions")

    assert res.status_code == 200
    assert [s["id"] for s in res.json()] == ["sess-case"]


def test_list_sessions_resolve_failure_falls_back_to_normcase_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeCodingSessionBackend(
        cwd=Path("/Workspace"),
        model="gpt-4o",
        provider_name="openai",
        sessions=[
            {
                "id": "sess-text",
                "startTime": "2026-08-21T10:00:00",
                "messageCount": 4,
                "cwd": str(Path("/Other-Workspace")),
            }
        ],
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    client = _build_client(session)

    def _broken_resolve(self: Path) -> Path:
        raise OSError("resolve unavailable")

    monkeypatch.setattr(Path, "resolve", _broken_resolve)

    res = client.get("/api/sessions")

    # resolve 异常只退化为规范化文本比较，不回退为全量 sessions
    assert res.status_code == 200
    assert res.json() == []


def test_resume_rejects_cross_workspace_and_unknown_ids() -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    cross = client.post("/api/sessions/resume", json={"session_id": "sess-2"})
    unknown = client.post("/api/sessions/resume", json={"session_id": "sess-404"})

    assert cross.status_code == 404
    assert unknown.status_code == 404
    assert cross.json() == unknown.json()
    assert ("resume", "sess-2") not in backend.session_operations
    assert ("resume", "sess-404") not in backend.session_operations


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


def test_get_messages_and_open_resource_project_safe_tool_result(
    tmp_path: Path,
) -> None:
    backend = FakeCodingSessionBackend(cwd=tmp_path)
    persisted = tmp_path / "tool-result.txt"
    persisted.write_bytes(b"full result\n")
    backend.messages = (
        AssistantMessage(
            content=[
                ToolCall(
                    id="tool-1",
                    name="read_file",
                    arguments={"file_path": "tool-result.txt"},
                )
            ]
        ),
        ToolResultMessage(
            tool_call_id="tool-1",
            tool_name="read_file",
            content="preview",
            details={
                "persisted_path": str(persisted),
                "original_bytes": len("full result\n".encode("utf-8")),
            },
        ),
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    client = _build_client(session)

    history = client.get("/api/messages")
    assert history.status_code == 200
    tool = history.json()[0]["tools"][0]
    assert tool["openable"] == {
        "path": str(persisted),
        "expectedSize": len("full result\n".encode("utf-8")),
    }

    opened = client.get(
        "/api/resources/open",
        params={"path": str(persisted), "expected_size": len("full result\n".encode("utf-8"))},
    )
    assert opened.status_code == 200
    assert opened.json()["status"] == "ready"
    assert opened.json()["content"] == "full result\n"


def test_open_resource_is_a_sync_threadpool_endpoint() -> None:
    session, _ = _build_test_session()
    app = create_app(session, capability=_CAPABILITY)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/resources/open")

    assert not inspect.iscoroutinefunction(route.endpoint)


def test_set_thinking_level() -> None:
    session, _ = _build_test_session()
    client = _build_client(session)

    # 切换 thinking
    res_think = client.post("/api/thinking", json={"level": "high"})
    assert res_think.status_code == 200
    assert res_think.json()["thinking_level"] == "high"


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把凭证持久化与 known_models 全部指向 tmp_path，并守护真实配置不变。"""
    real_config = Path.home() / ".lion-code" / "config.json"

    def _snapshot() -> tuple[bytes, float | None]:
        try:
            return real_config.read_bytes(), real_config.stat().st_mtime_ns
        except OSError:
            return b"", None

    before = _snapshot()
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(lion_config, "CONFIG_PATH", config_path)
    yield config_path
    assert _snapshot() == before, "测试不得改动真实 ~/.lion-code/config.json"


def test_configure_provider_model_only_keeps_credentials(
    isolated_config: Path,
) -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    res = client.post("/api/config/provider", json={"model": "gpt-4o-mini"})

    assert res.status_code == 200
    assert res.json()["model"] == "gpt-4o-mini"
    # Runtime 收到合并后的完整配置，同 Provider 更新保留现有 key/base URL
    assert backend.provider_configure_calls == [
        {
            "model": "gpt-4o-mini",
            "api_key": "sk-old",
            "use_openai": True,
            "api_base": "https://api.test/v1",
        }
    ]
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["model"] == "gpt-4o-mini"
    assert saved["api_key"] == "sk-old"
    assert saved["provider"] == "openai"
    assert saved["base_url"] == "https://api.test/v1"

    read_back = client.get("/api/config/provider")
    assert read_back.status_code == 200
    assert read_back.json() == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "sk-old",
        "base_url": "https://api.test/v1",
    }


def test_configure_provider_same_provider_with_empty_key_succeeds(
    isolated_config: Path,
) -> None:
    session, _ = _build_test_session()
    client = _build_client(session)

    res = client.post(
        "/api/config/provider",
        json={"model": "gpt-4o-mini", "api_key": ""},
    )

    assert res.status_code == 200
    assert (
        json.loads(isolated_config.read_text(encoding="utf-8"))["api_key"] == "sk-old"
    )


def test_configure_provider_switch_without_credentials_rejected(
    isolated_config: Path,
) -> None:
    session, backend = _build_test_session()
    backend.provider_config_data = {
        "use_openai": False,
        "model": "claude-3-5-sonnet",
        "api_key": "",
        "base_url": "",
    }
    client = _build_client(session)

    res = client.post("/api/config/provider", json={"provider": "openai"})

    assert res.status_code == 400
    assert backend.provider_configure_calls == []
    assert not isolated_config.exists()


def test_configure_provider_runtime_failure_leaves_both_sides_unchanged(
    isolated_config: Path,
) -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    def _fail(**kwargs: Any) -> None:
        raise RuntimeError("provider build failed")

    backend.configure_provider = _fail  # type: ignore[method-assign]

    res = client.post("/api/config/provider", json={"model": "gpt-4o-mini"})

    assert res.status_code == 400
    assert not isolated_config.exists()


def test_configure_provider_disk_failure_rolls_back_runtime(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    def _fail_save(**kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(server_app_module, "save_api_config", _fail_save)

    res = client.post("/api/config/provider", json={"model": "gpt-4o-mini"})

    assert res.status_code == 500
    # 第一次尝试新配置，写盘失败后补偿回滚到旧快照
    assert backend.provider_configure_calls[0]["model"] == "gpt-4o-mini"
    assert backend.provider_configure_calls[-1] == {
        "model": "gpt-4o",
        "api_key": "sk-old",
        "use_openai": True,
        "api_base": "https://api.test/v1",
    }
    assert backend.provider_config_data["model"] == "gpt-4o"


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
    missing_config = client.get("/api/config/provider")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert foreign_origin.status_code == 403
    assert foreign_host.status_code == 403
    assert vite_origin.status_code == 200
    assert missing_config.status_code == 401
    for response in (missing, wrong, foreign_origin, foreign_host):
        assert _CAPABILITY not in response.text
        assert _WRONG_CAPABILITY not in response.text
    assert "sk-old" not in missing_config.text


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
        update = next(e for e in received_events if e.get("type") == "message_update")
        assert "assistantMessageEvent" in update
        assert "assistant_message_event" not in update


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


def test_websocket_rejects_second_owner_without_disturbing_first() -> None:
    session, backend = _build_test_session()
    client = _build_client(session)
    connection: dict[str, Any] = {
        "subprotocols": _websocket_protocols(),
        "headers": {"Origin": _APP_ORIGIN},
    }

    with client.websocket_connect(_WS_URL, **connection) as first:
        first_confirm = backend.confirm_fn
        assert first_confirm is not None

        with pytest.raises(WebSocketDisconnect) as denial:
            with client.websocket_connect(_WS_URL, **connection):
                pass

        assert denial.value.code == 1008
        assert backend.confirm_fn is first_confirm
        first.send_text("not-json")
        assert first.receive_json() == {
            "type": "protocol_error",
            "message": "客户端消息不符合 WebSocket action 契约",
        }

    with client.websocket_connect(_WS_URL, **connection) as replacement:
        assert backend.confirm_fn is not None
        assert backend.confirm_fn is not first_confirm
        replacement.send_text("not-json")
        assert replacement.receive_json()["type"] == "protocol_error"


def test_websocket_plan_continue_and_compact_actions_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, backend = _build_test_session()
    client = _build_client(session)

    with client.websocket_connect(
        _WS_URL,
        subprotocols=_websocket_protocols(),
        headers={"Origin": _APP_ORIGIN},
    ) as websocket:
        websocket.send_json({"action": "command", "command": "/plan"})
        assert websocket.receive_json() == {
            "type": "notice",
            "text": "Plan mode toggled.",
            "role": "info",
        }
        assert backend.plan_mode is True

        async def compact_with_canonical_notice() -> None:
            backend.session_operations.append(("compact", None))
            assert backend.notice_fn is not None
            backend.notice_fn("Conversation compacted.", "info")

        monkeypatch.setattr(backend, "compact", compact_with_canonical_notice)
        websocket.send_json({"action": "compact"})
        assert websocket.receive_json() == {
            "type": "notice",
            "text": "Conversation compacted.",
            "role": "info",
        }
        assert ("compact", None) in backend.session_operations

        websocket.send_json({"action": "continue"})
        assert websocket.receive_json()["type"] == "agent_settled"
        assert backend.continue_calls == 1


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
    req_id = data.get("requestId")
    assert "rm -rf" in data.get("message", "")

    # 3. 模拟前端回复 confirm_response
    await bridge.handle_inbound_data(
        {"action": "confirm_response", "requestId": req_id, "approved": True}
    )

    # 4. 验证 confirm_fn 返回 True
    result = await confirm_task
    assert result is True

    await bridge.aclose()


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
    req_id = data.get("requestId")
    assert "Step A" in data.get("plan", "")

    # 前端选择 execute
    await bridge.handle_inbound_data(
        {
            "action": "plan_approval_response",
            "requestId": req_id,
            "choice": "execute",
            "feedback": None,
        }
    )

    result = await plan_task
    assert result == {"choice": "execute", "feedback": None}

    await bridge.aclose()


async def test_websocket_strict_actions_do_not_coerce_approval_values() -> None:
    session, backend = _build_test_session()
    websocket = MockWebSocket()
    bridge = SessionWebsocketBridge(session, websocket)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    assert backend.confirm_fn is not None
    confirm_task = asyncio.create_task(backend.confirm_fn("Approve?"))
    await asyncio.sleep(0)
    request_id = json.loads(websocket.sent_texts[0])["requestId"]

    await bridge.handle_inbound_data(
        {
            "action": "confirm_response",
            "requestId": request_id,
            "approved": "false",
        }
    )

    assert confirm_task.done() is False
    assert json.loads(websocket.sent_texts[-1])["type"] == "protocol_error"

    await bridge.handle_inbound_data(
        {
            "action": "confirm_response",
            "request_id": request_id,
            "approved": False,
        }
    )

    assert confirm_task.done() is False
    assert json.loads(websocket.sent_texts[-1])["type"] == "protocol_error"

    await bridge.handle_inbound_data(
        {
            "action": "confirm_response",
            "requestId": request_id,
            "approved": False,
        }
    )
    assert await confirm_task is False
    await bridge.aclose()


async def test_websocket_strict_actions_reject_invalid_plan_choice_and_extra_fields() -> (
    None
):
    session, backend = _build_test_session()
    websocket = MockWebSocket()
    bridge = SessionWebsocketBridge(session, websocket)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    assert backend.plan_approval_fn is not None
    approval_task = asyncio.create_task(backend.plan_approval_fn("Plan"))
    await asyncio.sleep(0)
    request_id = json.loads(websocket.sent_texts[0])["requestId"]

    await bridge.handle_inbound_data(
        {
            "action": "plan_approval_response",
            "requestId": request_id,
            "choice": "ship-it",
        }
    )
    await bridge.handle_inbound_data({"action": "cancel", "unexpected": True})

    assert approval_task.done() is False
    assert [json.loads(item)["type"] for item in websocket.sent_texts[-2:]] == [
        "protocol_error",
        "protocol_error",
    ]

    await bridge.aclose()
    assert await approval_task == {"choice": "keep-planning"}


async def test_websocket_cancel_denies_pending_approval() -> None:
    session, backend = _build_test_session()
    websocket = MockWebSocket()
    bridge = SessionWebsocketBridge(session, websocket)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    assert backend.confirm_fn is not None
    confirm_task = asyncio.create_task(backend.confirm_fn("Approve?"))
    await asyncio.sleep(0)

    await bridge.handle_inbound_data({"action": "cancel"})

    assert await confirm_task is False
    assert backend.cancel_calls == 1
    await bridge.aclose()


async def test_websocket_close_cancels_run_denies_pending_and_unbinds_once() -> None:
    session, backend = _build_test_session()
    backend.wait_for_cancel = True
    websocket = MockWebSocket()
    bridge = SessionWebsocketBridge(session, websocket)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    await bridge.handle_inbound_data({"action": "prompt", "prompt": "work"})
    await bridge.handle_inbound_data({"action": "prompt", "prompt": "duplicate"})
    assert json.loads(websocket.sent_texts[-1])["type"] == "protocol_error"
    await asyncio.wait_for(backend.prompt_started.wait(), timeout=1)
    assert backend.confirm_fn is not None
    confirm_task = asyncio.create_task(backend.confirm_fn("Approve?"))
    await asyncio.sleep(0)

    await asyncio.wait_for(bridge.aclose(), timeout=1)
    await bridge.aclose()

    assert await confirm_task is False
    assert backend.cancel_calls == 1
    assert backend.prompt_calls == 1
    assert session.is_running is False
    assert backend.confirm_fn is None
    assert backend.plan_approval_fn is None
    assert backend.notice_fn is None


async def test_websocket_close_cancels_pending_notice_task() -> None:
    session, backend = _build_test_session()
    websocket = BlockingMockWebSocket()
    bridge = SessionWebsocketBridge(session, websocket)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    assert backend.notice_fn is not None
    backend.notice_fn("notice", "info")
    await asyncio.wait_for(websocket.send_started.wait(), timeout=1)

    await asyncio.wait_for(bridge.aclose(), timeout=1)

    assert websocket.send_cancelled is True
    assert backend.notice_fn is None


async def test_websocket_close_unblocks_run_waiting_behind_notice_send() -> None:
    session, backend = _build_test_session()
    backend.wait_for_cancel = True
    websocket = BlockingMockWebSocket()
    bridge = SessionWebsocketBridge(session, websocket)  # type: ignore[arg-type]
    bridge.bind_callbacks()

    assert backend.notice_fn is not None
    backend.notice_fn("notice", "info")
    await asyncio.wait_for(websocket.send_started.wait(), timeout=1)
    await bridge.handle_inbound_data({"action": "prompt", "prompt": "work"})
    await asyncio.wait_for(backend.prompt_started.wait(), timeout=1)

    await asyncio.wait_for(bridge.aclose(), timeout=1)

    assert websocket.send_cancelled is True
    assert backend.cancel_calls == 1
    assert session.is_running is False


def test_lifespan_shutdown_closes_session_exactly_once() -> None:
    session, backend = _build_test_session()
    app = create_app(session, capability=_CAPABILITY)

    with TestClient(app, base_url=_APP_ORIGIN) as client:
        assert client.get("/api/health").status_code == 200
    assert backend.closed is True
    assert backend.aclose_calls == 1

    async def _second_lifespan_cycle() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(_second_lifespan_cycle())
    assert backend.aclose_calls == 1


def test_websocket_lease_exposes_current_owner() -> None:
    # 只验证对象身份语义，不构造真实 bridge
    from lion_code.server.bridge import SessionWebsocketBridge, WebsocketConnectionLease

    lease = WebsocketConnectionLease()
    first = cast(SessionWebsocketBridge, object())
    second = cast(SessionWebsocketBridge, object())

    assert lease.owner is None
    assert lease.acquire(first) is True
    assert lease.owner is first
    lease.release(first)
    assert lease.owner is None
    assert lease.acquire(second) is True
    lease.release(first)
    assert lease.owner is second
