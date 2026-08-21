from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic import BaseModel
from starlette.websockets import WebSocket

from lion_code.application.session import LionCodingSession

from .models import (
    ConfirmRequestEvent,
    NoticeEvent,
    PlanApprovalRequestEvent,
    ServerErrorEvent,
)


class SessionWebsocketBridge:
    """双向流式与审批挂起调度桥。"""

    def __init__(self, session: LionCodingSession, websocket: WebSocket) -> None:
        self._session = session
        self._ws = websocket
        self._pending_confirms: dict[str, asyncio.Future[bool]] = {}
        self._pending_plan_approvals: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()
        self._active_run_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def bind_callbacks(self) -> None:
        """把 LionCodingSession 的交互回调绑定到本 Bridge。"""
        self._session.set_confirm_fn(self._on_confirm)
        self._session.set_plan_approval_fn(self._on_plan_approval)
        self._session.set_notice_fn(self._on_notice)

    def unbind_callbacks(self) -> None:
        """清理已绑定的回调，并取消所有待审批挂起项。"""
        self._session.set_confirm_fn(None)
        self._session.set_plan_approval_fn(None)
        self._session.set_notice_fn(None)

        # 解除所有挂起中的审批，默认返回 False/中止
        for fut in self._pending_confirms.values():
            if not fut.done():
                fut.set_result(False)
        self._pending_confirms.clear()

        for fut in self._pending_plan_approvals.values():
            if not fut.done():
                fut.set_result({"choice": "keep-planning"})
        self._pending_plan_approvals.clear()

    async def send_model(self, model: BaseModel) -> None:
        """线程/并发安全地发送 Pydantic 模型。"""
        async with self._send_lock:
            await self._ws.send_text(model.model_dump_json(by_alias=True))

    async def send_text(self, text: str) -> None:
        """线程/并发安全地发送原始 JSON 字符串。"""
        async with self._send_lock:
            await self._ws.send_text(text)

    # ─── 回调注入实现 ─────────────────────────────────────────

    async def _on_confirm(self, message: str) -> bool:
        req_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        self._pending_confirms[req_id] = fut
        try:
            await self.send_model(
                ConfirmRequestEvent(request_id=req_id, message=message)
            )
            return await fut
        finally:
            self._pending_confirms.pop(req_id, None)

    async def _on_plan_approval(self, plan: str) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_plan_approvals[req_id] = fut
        try:
            await self.send_model(
                PlanApprovalRequestEvent(request_id=req_id, plan=plan)
            )
            return await fut
        finally:
            self._pending_plan_approvals.pop(req_id, None)

    def _on_notice(self, text: str, role: str) -> None:
        task = asyncio.create_task(
            self.send_model(
                NoticeEvent(
                    text=text,
                    role="error" if role == "error" else ("info" if role == "info" else "status"),
                )
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ─── 消息分发 ─────────────────────────────────────────────

    async def handle_inbound_data(self, data: dict[str, Any]) -> None:
        action = data.get("action")

        if action == "prompt":
            prompt_text = str(data.get("prompt", "")).strip()
            streaming_behavior = data.get("streaming_behavior")
            if not prompt_text:
                return

            if self._session.is_running:
                # 运行中插话或追问
                behavior = streaming_behavior if streaming_behavior in {"steer", "follow_up"} else "steer"
                async for event in self._session.prompt(prompt_text, streaming_behavior=behavior):  # type: ignore[arg-type]
                    await self.send_text(event.model_dump_json(by_alias=True))
                return

            # 空闲时驱动新一轮
            self._active_run_task = asyncio.create_task(self._drive_prompt(prompt_text))

        elif action == "continue":
            if not self._session.is_running:
                self._active_run_task = asyncio.create_task(self._drive_continue())

        elif action == "cancel":
            self._session.cancel()

        elif action == "confirm_response":
            req_id = str(data.get("request_id", ""))
            approved = bool(data.get("approved", False))
            fut = self._pending_confirms.get(req_id)
            if fut and not fut.done():
                fut.set_result(approved)

        elif action == "plan_approval_response":
            req_id = str(data.get("request_id", ""))
            choice = str(data.get("choice", "keep-planning"))
            feedback = data.get("feedback")
            fut_plan = self._pending_plan_approvals.get(req_id)
            if fut_plan and not fut_plan.done():
                fut_plan.set_result({"choice": choice, "feedback": feedback})

        elif action == "compact":
            try:
                await self._session.compact()
                await self.send_model(NoticeEvent(text="Conversation compacted.", role="info"))
            except Exception as e:
                await self.send_model(NoticeEvent(text=f"Compact failed: {e}", role="error"))

        elif action == "command":
            cmd = str(data.get("command", ""))
            result = self._session.handle_command(cmd)
            if result.message:
                await self.send_model(NoticeEvent(text=result.message, role="info"))

    async def _drive_prompt(self, text: str) -> None:
        try:
            async for event in self._session.prompt(text):
                await self.send_text(event.model_dump_json(by_alias=True))
        except Exception as exc:
            await self.send_model(ServerErrorEvent(error=str(exc)))

    async def _drive_continue(self) -> None:
        try:
            async for event in self._session.continue_():
                await self.send_text(event.model_dump_json(by_alias=True))
        except Exception as exc:
            await self.send_model(ServerErrorEvent(error=str(exc)))
