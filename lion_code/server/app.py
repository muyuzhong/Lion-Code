"""Electron sidecar 使用的 API 与 WebSocket 服务端。"""

from __future__ import annotations

import os
import re
import secrets
from contextlib import asynccontextmanager
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
from starlette.websockets import WebSocketState

from lion_code.application.session import LionCodingSession
from lion_code.config import save_api_config
from lion_code.core.messages import AssistantMessage, ToolResultMessage, UserMessage

from .bridge import SessionWebsocketBridge, WebsocketConnectionLease
from .models import (
    ChatMessageDTO,
    ModelChoiceItem,
    ProviderConfigRequest,
    ProviderConfigResponse,
    RenameSessionRequest,
    ResumeSessionRequest,
    ServerStatusResponse,
    SessionSummaryItem,
    SkillItem,
    ThinkingLevelRequest,
    ToolCallDTO,
)

_LOOPBACK_HOST = "127.0.0.1"
_VITE_ORIGIN = "http://127.0.0.1:3000"
# Electron Renderer 通过受限自定义协议加载，Origin 固定为该值。
_DESKTOP_ORIGIN = "lion://app"
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


def generate_capability() -> str:
    return secrets.token_urlsafe(32)


def create_app(
    session: LionCodingSession,
    *,
    capability: str,
    port: int = 8000,
) -> FastAPI:
    """创建仅接受本机 capability 客户端的 API-only 应用。

    健康检查保持公开，其余 REST/WS 控制面共享传入的进程内 capability。
    函数不持久化或输出该值；格式不符合 URL-safe token 契约时抛出
    ``ValueError``。进程关闭时按「活动连接 → Session」顺序各关闭一次。
    """
    if _CAPABILITY_PATTERN.fullmatch(capability) is None:
        raise ValueError("capability 必须是 URL-safe token")

    websocket_lease = WebsocketConnectionLease()
    session_closed = False

    async def _shutdown_once() -> None:
        nonlocal session_closed
        if session_closed:
            return
        session_closed = True
        owner = websocket_lease.owner
        if owner is not None:
            await owner.aclose()
        await session.aclose()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        await _shutdown_once()

    app_origin = _http_origin(port)
    expected_host = _expected_host(port)
    allowed_origins = frozenset((app_origin, _VITE_ORIGIN, _DESKTOP_ORIGIN))
    app = FastAPI(
        title="Lion Code Desktop API",
        description="Lion Code 桌面 sidecar 的 REST 与 WebSocket 控制面",
        version="1.0.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

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

    def _is_same_workspace(meta_cwd: str | None) -> bool:
        """list 与 resume 共用的当前 cwd eligibility 判断。

        无 cwd 的 legacy session 保持可恢复；resolve 异常时退化为
        normcase 规范化路径文本比较，绝不扩大到其他 workspace。
        """
        if not meta_cwd:
            return True
        try:
            return os.path.normcase(str(Path(meta_cwd).resolve())) == os.path.normcase(
                str(session.cwd.resolve())
            )
        except Exception:
            return os.path.normcase(str(Path(meta_cwd))) == os.path.normcase(
                str(session.cwd)
            )

    async def _eligible_sessions() -> list[dict]:
        """只保留属于当前 cwd 的会话元数据；零匹配返回空列表。"""
        sessions_meta = await session.list_sessions()
        return [m for m in sessions_meta if _is_same_workspace(m.get("cwd"))]

    @api.get("/sessions", response_model=list[SessionSummaryItem])
    async def list_sessions() -> list[SessionSummaryItem]:
        filtered = await _eligible_sessions()
        filtered.sort(key=lambda m: m.get("startTime", ""), reverse=True)
        return [
            SessionSummaryItem(
                id=str(m.get("id", "")),
                label=m.get("label"),
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
        # 与 list 同一 eligibility 判断：跨 workspace 的 id 与不存在的 id
        # 返回同一 404，不泄漏存在性差异。
        eligible_ids = {str(m.get("id", "")) for m in await _eligible_sessions()}
        if body.session_id not in eligible_ids:
            raise HTTPException(status_code=404, detail="恢复会话失败或会话不存在")
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

    @api.post("/sessions/rename")
    async def rename_session(body: RenameSessionRequest) -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话正在运行中，无法重命名")
        eligible_ids = {str(m.get("id", "")) for m in await _eligible_sessions()}
        if body.session_id not in eligible_ids:
            raise HTTPException(status_code=404, detail="会话不存在")
        label = body.label.strip()
        if not label:
            raise HTTPException(status_code=422, detail="会话名称不能为空")
        if not await session.rename_session(body.session_id, label):
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"success": True, "session_id": body.session_id, "label": label}

    @api.get("/models", response_model=list[ModelChoiceItem])
    async def get_models() -> list[ModelChoiceItem]:
        return [
            ModelChoiceItem(provider_name=c.provider_name, model=c.model)
            for c in session.available_model_choices
        ]

    @api.get("/config/provider", response_model=ProviderConfigResponse)
    async def get_provider_config() -> ProviderConfigResponse:
        snapshot = session.get_provider_config()
        return ProviderConfigResponse(
            provider="openai" if snapshot.get("use_openai") else "anthropic",
            model=str(snapshot.get("model") or session.model),
            api_key=str(snapshot.get("api_key") or ""),
            base_url=str(snapshot.get("base_url") or ""),
        )

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

        use_openai = body.provider == "openai" if body.provider else current_use_openai
        target_model = body.model or current_model
        target_api_key = body.api_key or current_api_key
        target_base_url = body.base_url or current_base_url

        # 切换 Provider 时校验目标凭证；缺失直接拒绝，不动 Runtime 与磁盘。
        provider_switched = (
            body.provider is not None and use_openai != current_use_openai
        )
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
                rollback["api_base" if current_use_openai else "anthropic_base_url"] = (
                    current_base_url
                )
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

    return app
