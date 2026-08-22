"""FastAPI Web 服务端实现。"""

from __future__ import annotations

import re
import secrets
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from lion_code.application.session import LionCodingSession
from lion_code.config import save_api_config
from lion_code.core.messages import AssistantMessage, ToolResultMessage, UserMessage

from .bridge import SessionWebsocketBridge, WebsocketConnectionLease
from .models import (
    ChatMessageDTO,
    ModelChoiceItem,
    ProviderConfigRequest,
    ResumeSessionRequest,
    ServerStatusResponse,
    SessionSummaryItem,
    SkillItem,
    ThinkingLevelRequest,
    ToolCallDTO,
)

_LOOPBACK_HOST = "127.0.0.1"
_VITE_ORIGIN = "http://127.0.0.1:3000"
_WEBSOCKET_PROTOCOL = "lion-code"
_WEBSOCKET_CAPABILITY_PREFIX = "lion-code-capability."
_CAPABILITY_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}")


def _http_origin(port: int) -> str:
    suffix = "" if port == 80 else f":{port}"
    return f"http://{_LOOPBACK_HOST}{suffix}"


def _expected_host(port: int) -> str:
    return _LOOPBACK_HOST if port == 80 else f"{_LOOPBACK_HOST}:{port}"


def _is_local_request(
    *,
    host: str | None,
    origin: str | None,
    expected_host: str,
    allowed_origins: frozenset[str],
    require_origin: bool,
) -> bool:
    if host != expected_host:
        return False
    if origin is None:
        return not require_origin
    return origin in allowed_origins


def _has_bearer_capability(authorization: str | None, capability: str) -> bool:
    if authorization is None:
        return False
    scheme, separator, candidate = authorization.partition(" ")
    return (
        bool(separator)
        and scheme.lower() == "bearer"
        and _CAPABILITY_PATTERN.fullmatch(candidate) is not None
        and secrets.compare_digest(candidate, capability)
    )


def _has_websocket_capability(protocol_header: str | None, capability: str) -> bool:
    if protocol_header is None:
        return False
    expected_capability = f"{_WEBSOCKET_CAPABILITY_PREFIX}{capability}"
    protocols = tuple(item.strip() for item in protocol_header.split(","))
    return _WEBSOCKET_PROTOCOL in protocols and any(
        secrets.compare_digest(protocol, expected_capability) for protocol in protocols
    )


def _generate_capability() -> str:
    return secrets.token_urlsafe(32)


def _browser_url(port: int, capability: str) -> str:
    return f"{_http_origin(port)}/#capability={capability}"


def create_app(
    session: LionCodingSession,
    *,
    capability: str,
    port: int = 8000,
) -> FastAPI:
    """创建仅接受本机 capability 客户端的应用。

    静态页面与健康检查保持公开，其余 REST/WS 控制面共享传入的进程内
    capability。函数不持久化或输出该值；格式不符合 URL-safe token 契约时抛出
    ``ValueError``。
    """
    if _CAPABILITY_PATTERN.fullmatch(capability) is None:
        raise ValueError("capability 必须是 URL-safe token")

    app_origin = _http_origin(port)
    expected_host = _expected_host(port)
    allowed_origins = frozenset((app_origin, _VITE_ORIGIN))
    app = FastAPI(
        title="Lion Code Web API",
        description="Lion Code 编码 Agent 的 Web 与 WebSocket 服务端",
        version="1.0.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    websocket_lease = WebsocketConnectionLease()

    # ─── REST 接口 ───────────────────────────────────────────────

    @app.get("/api/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    async def require_local_capability(request: Request) -> None:
        if not _is_local_request(
            host=request.headers.get("host"),
            origin=request.headers.get("origin"),
            expected_host=expected_host,
            allowed_origins=allowed_origins,
            require_origin=False,
        ):
            raise HTTPException(status_code=403, detail="拒绝非本机请求")
        if not _has_bearer_capability(request.headers.get("authorization"), capability):
            raise HTTPException(
                status_code=401,
                detail="需要本机访问凭证",
                headers={"WWW-Authenticate": "Bearer"},
            )

    api = APIRouter(
        prefix="/api",
        dependencies=[Depends(require_local_capability)],
    )

    @api.get("/status", response_model=ServerStatusResponse)
    async def get_status() -> ServerStatusResponse:
        usage = session.token_usage()
        return ServerStatusResponse(
            session_id=session.session_id,
            model=session.model,
            provider_name=session.provider_name,
            permission_mode=session.permission_mode,
            api_configured=session.api_configured,
            cwd=str(session.cwd),
            thinking_level=session.thinking_level,
            available_thinking_levels=list(session.available_thinking_levels),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            is_running=session.is_running,
        )

    @api.get("/messages", response_model=list[ChatMessageDTO])
    async def get_messages() -> list[ChatMessageDTO]:
        raw_messages = session.messages
        result: list[ChatMessageDTO] = []

        tool_results: dict[str, tuple[str, bool]] = {}
        for m in raw_messages:
            if isinstance(m, ToolResultMessage):
                tool_results[m.tool_call_id] = (m.text, m.is_error)

        for i, m in enumerate(raw_messages):
            if isinstance(m, UserMessage):
                result.append(
                    ChatMessageDTO(
                        id=f"msg-{i}",
                        role="user",
                        content=m.text,
                        createdAt=None,
                    )
                )
            elif isinstance(m, AssistantMessage):
                tools_dto: list[ToolCallDTO] = []
                for tc in m.tool_calls:
                    res_tuple = tool_results.get(tc.id)
                    status: Literal["completed", "error"] = (
                        "error" if res_tuple and res_tuple[1] else "completed"
                    )
                    tools_dto.append(
                        ToolCallDTO(
                            id=tc.id,
                            toolName=tc.name,
                            args=tc.arguments,
                            status=status,
                            result=res_tuple[0] if res_tuple else None,
                        )
                    )
                result.append(
                    ChatMessageDTO(
                        id=f"msg-{i}",
                        role="assistant",
                        content=m.text,
                        reasoning=m.thinking_text or None,
                        tools=tools_dto,
                        error=m.error_message,
                        createdAt=None,
                    )
                )
        return result

    @api.get("/sessions", response_model=list[SessionSummaryItem])
    async def list_sessions() -> list[SessionSummaryItem]:
        sessions_meta = await session.list_sessions()
        current_cwd = session.cwd

        def _is_match(meta_cwd: str | None) -> bool:
            if not meta_cwd:
                return True
            try:
                return Path(meta_cwd).resolve() == current_cwd.resolve()
            except Exception:
                return str(meta_cwd).lower() == str(current_cwd).lower()

        filtered = [m for m in sessions_meta if _is_match(m.get("cwd"))]
        if not filtered and sessions_meta:
            filtered = list(sessions_meta)

        filtered.sort(key=lambda m: m.get("startTime", ""), reverse=True)
        return [
            SessionSummaryItem(
                id=str(m.get("id", "")),
                startTime=m.get("startTime"),
                messageCount=m.get("messageCount", 0),
                cwd=m.get("cwd"),
            )
            for m in filtered
        ]

    @api.post("/sessions/resume")
    async def resume_session(body: ResumeSessionRequest) -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话正在运行中，无法切换")
        success = await session.resume(body.session_id)
        if not success:
            raise HTTPException(status_code=404, detail="恢复会话失败或会话不存在")
        return {"success": True, "session_id": session.session_id}

    @api.post("/sessions/new")
    async def new_session() -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(
                status_code=400, detail="会话正在运行中，无法创建新会话"
            )
        await session.new_session()
        return {"success": True, "session_id": session.session_id}

    @api.get("/models", response_model=list[ModelChoiceItem])
    async def get_models() -> list[ModelChoiceItem]:
        return [
            ModelChoiceItem(provider_name=c.provider_name, model=c.model)
            for c in session.available_model_choices
        ]

    @api.post("/config/provider")
    async def configure_provider(body: ProviderConfigRequest) -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话运行中，无法修改配置")

        # 局部请求先与当前快照合并成完整目标配置；空字段一律保留现有值。
        snapshot = session.get_provider_config()
        current_use_openai = bool(snapshot.get("use_openai"))
        current_model = str(snapshot.get("model") or session.model)
        current_api_key = str(snapshot.get("api_key") or "")
        current_base_url = str(snapshot.get("base_url") or "")

        use_openai = (
            body.provider == "openai" if body.provider else current_use_openai
        )
        target_model = body.model or current_model
        target_api_key = body.api_key or current_api_key
        target_base_url = body.base_url or current_base_url

        # 切换 Provider 时校验目标凭证；缺失直接拒绝，不动 Runtime 与磁盘。
        provider_switched = body.provider is not None and use_openai != current_use_openai
        if provider_switched:
            if not target_api_key or (use_openai and not target_base_url):
                raise HTTPException(
                    status_code=400,
                    detail="切换 Provider 需要目标凭证（API key 及 base URL）",
                )

        agent_kwargs: dict[str, Any] = {
            "model": target_model,
            "api_key": target_api_key,
            "use_openai": use_openai,
        }
        if target_base_url:
            base_url_key = "api_base" if use_openai else "anthropic_base_url"
            agent_kwargs[base_url_key] = target_base_url

        def _rollback_kwargs() -> dict[str, Any]:
            rollback: dict[str, Any] = {
                "model": current_model,
                "api_key": current_api_key,
                "use_openai": current_use_openai,
            }
            if current_base_url:
                rollback[
                    "api_base" if current_use_openai else "anthropic_base_url"
                ] = current_base_url
            return rollback

        try:
            session.configure_provider(**agent_kwargs)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Provider 配置失败: {exc}"
            ) from exc

        try:
            save_api_config(
                provider="openai" if use_openai else "anthropic",
                model=target_model,
                api_key=target_api_key,
                base_url=target_base_url,
            )
        except Exception as exc:
            # 写盘失败必须补偿：Runtime 回滚到旧快照，两侧保持一致。
            session.configure_provider(**_rollback_kwargs())
            raise HTTPException(
                status_code=500, detail="配置写入失败，已回滚到原配置"
            ) from exc

        return {
            "success": True,
            "model": session.model,
            "provider": session.provider_name,
        }

    @api.get("/skills", response_model=list[SkillItem])
    async def get_skills() -> list[SkillItem]:
        return [
            SkillItem(name=s.name, description=s.description) for s in session.skills
        ]

    @api.post("/thinking")
    async def set_thinking(body: ThinkingLevelRequest) -> dict[str, str]:
        if session.is_running:
            raise HTTPException(
                status_code=400, detail="会话运行中，无法切换 thinking 档位"
            )
        effective = session.set_thinking_level(body.level)
        return {"thinking_level": effective}

    app.include_router(api)

    # ─── WebSocket 流式接口 ───────────────────────────────────────

    @app.websocket("/ws/chat")
    async def websocket_chat_endpoint(websocket: WebSocket) -> None:
        if not _is_local_request(
            host=websocket.headers.get("host"),
            origin=websocket.headers.get("origin"),
            expected_host=expected_host,
            allowed_origins=allowed_origins,
            require_origin=True,
        ) or not _has_websocket_capability(
            websocket.headers.get("sec-websocket-protocol"), capability
        ):
            await websocket.close(code=1008)
            return

        bridge = SessionWebsocketBridge(session, websocket)
        if not websocket_lease.acquire(bridge):
            await websocket.close(code=1008)
            return

        try:
            await websocket.accept(subprotocol=_WEBSOCKET_PROTOCOL)
            bridge.bind_callbacks()
            while True:
                message_text = await websocket.receive_text()
                await bridge.handle_inbound_text(message_text)
        except (WebSocketDisconnect, ConnectionResetError):
            pass
        finally:
            await bridge.aclose()
            websocket_lease.release(bridge)
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()

    # ─── 静态前端页面挂载 (如果已构建 frontend/dist) ──────────────
    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    return app


def run_server(
    session: LionCodingSession,
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """在固定 loopback 地址阻塞运行服务，并生成一次性进程 capability。

    ``open_browser`` 启用时会启动后台线程，用仅在 fragment 中携带 capability
    的 URL 打开默认浏览器。禁用时不交付 capability，也不提供匿名 bootstrap；
    headless 客户端只能使用公开 health，不能访问控制面。服务停止前该函数不会返回。
    """
    import uvicorn

    capability = _generate_capability()
    app = create_app(session=session, capability=capability, port=port)

    if open_browser:
        url = _browser_url(port, capability)

        def _open() -> None:
            time.sleep(0.6)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=_LOOPBACK_HOST, port=port, log_level="info")
