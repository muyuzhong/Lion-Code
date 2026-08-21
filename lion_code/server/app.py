"""FastAPI Web 服务端实现。"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from lion_code.application.session import LionCodingSession
from lion_code.config import save_api_config

from .bridge import SessionWebsocketBridge
from .models import (
    ModelChoiceItem,
    ProviderConfigRequest,
    ResumeSessionRequest,
    ServerStatusResponse,
    SessionSummaryItem,
    SkillItem,
    ThinkingLevelRequest,
)


def create_app(session: LionCodingSession) -> FastAPI:
    """创建并配置用于 Lion Code 的 FastAPI 应用。"""
    app = FastAPI(
        title="Lion Code Web API",
        description="Lion Code 编码 Agent 的 Web 与 WebSocket 服务端",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── REST 接口 ───────────────────────────────────────────────

    @app.get("/api/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status", response_model=ServerStatusResponse)
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

    @app.get("/api/sessions", response_model=list[SessionSummaryItem])
    async def list_sessions() -> list[SessionSummaryItem]:
        sessions_meta = await session.list_sessions()
        cwd_str = str(session.cwd)
        filtered = [m for m in sessions_meta if m.get("cwd") == cwd_str]
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

    @app.post("/api/sessions/resume")
    async def resume_session(body: ResumeSessionRequest) -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话正在运行中，无法切换")
        success = await session.resume(body.session_id)
        if not success:
            raise HTTPException(status_code=404, detail="恢复会话失败或会话不存在")
        return {"success": True, "session_id": session.session_id}

    @app.post("/api/sessions/new")
    async def new_session() -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话正在运行中，无法创建新会话")
        await session.new_session()
        return {"success": True, "session_id": session.session_id}

    @app.get("/api/models", response_model=list[ModelChoiceItem])
    async def get_models() -> list[ModelChoiceItem]:
        return [
            ModelChoiceItem(provider_name=c.provider_name, model=c.model)
            for c in session.available_model_choices
        ]

    @app.post("/api/config/provider")
    async def configure_provider(body: ProviderConfigRequest) -> dict[str, Any]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话运行中，无法修改配置")

        agent_kwargs: dict[str, Any] = {}
        config_kwargs: dict[str, Any] = {}

        if body.model:
            agent_kwargs["model"] = body.model
            config_kwargs["model"] = body.model

        if body.api_key:
            agent_kwargs["api_key"] = body.api_key
            config_kwargs["api_key"] = body.api_key

        if body.provider:
            use_openai = body.provider == "openai"
            agent_kwargs["use_openai"] = use_openai
            config_kwargs["provider"] = body.provider
            if use_openai and body.base_url:
                agent_kwargs["api_base"] = body.base_url
                config_kwargs["base_url"] = body.base_url
            elif not use_openai and body.base_url:
                agent_kwargs["anthropic_base_url"] = body.base_url
                config_kwargs["base_url"] = body.base_url

        if agent_kwargs:
            session.configure_provider(**agent_kwargs)
        if config_kwargs:
            save_api_config(**config_kwargs)

        return {"success": True, "model": session.model, "provider": session.provider_name}

    @app.get("/api/skills", response_model=list[SkillItem])
    async def get_skills() -> list[SkillItem]:
        return [
            SkillItem(name=s.name, description=s.description)
            for s in session.skills
        ]

    @app.post("/api/thinking")
    async def set_thinking(body: ThinkingLevelRequest) -> dict[str, str]:
        if session.is_running:
            raise HTTPException(status_code=400, detail="会话运行中，无法切换 thinking 档位")
        effective = session.set_thinking_level(body.level)
        return {"thinking_level": effective}

    # ─── WebSocket 流式接口 ───────────────────────────────────────

    @app.websocket("/ws/chat")
    async def websocket_chat_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        bridge = SessionWebsocketBridge(session, websocket)
        bridge.bind_callbacks()

        try:
            while True:
                message_text = await websocket.receive_text()
                try:
                    data = json.loads(message_text)
                except Exception:
                    continue

                if isinstance(data, dict):
                    await bridge.handle_inbound_data(data)
        except (WebSocketDisconnect, ConnectionResetError):
            pass
        finally:
            bridge.unbind_callbacks()
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()

    # ─── 静态前端页面挂载 (如果已构建 frontend/dist) ──────────────
    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    return app


def run_server(
    session: LionCodingSession,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """启动 uvicorn 服务并可选自动打开浏览器。"""
    import uvicorn

    app = create_app(session=session)
    url = f"http://{host}:{port}"

    if open_browser:
        def _open() -> None:
            time.sleep(0.6)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
