from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocket

from lion_code.application.session import LionCodingSession

from .models import (
    CLIENT_ACTION_ADAPTER,
    CancelAction,
    ClientAction,
    CommandAction,
    CompactAction,
    ConfirmRequestEvent,
    ConfirmResponseAction,
    ContinueAction,
    FollowUpAction,
    NoticeEvent,
    PlanApprovalRequestEvent,
    PlanApprovalResponseAction,
    PromptAction,
    ProtocolErrorEvent,
    ServerErrorEvent,
    SteerAction,
)


class SessionWebsocketBridge:
    """单个浏览器连接拥有的流式、审批与后台任务边界。"""

    def __init__(self, session: LionCodingSession, websocket: WebSocket) -> None:
        self._session = session
        self._ws = websocket
        self._pending_confirms: dict[str, asyncio.Future[bool]] = {}
        self._pending_plan_approvals: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._active_run_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._bound = False
        self._closed = False

    def bind_callbacks(self) -> None:
        """把 Session 交互回调绑定到当前连接 owner。"""
        if self._closed:
            raise RuntimeError("WebSocket bridge 已关闭")
        if self._bound:
            return
        self._session.set_confirm_fn(self._on_confirm)
        self._session.set_plan_approval_fn(self._on_plan_approval)
        self._session.set_notice_fn(self._on_notice)
        self._bound = True

    async def aclose(self) -> None:
        """按 deny、cancel、await、unbind 顺序幂等收敛连接状态。"""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._deny_pending_requests()

            active_run = self._active_run_task
            if active_run is not None and not active_run.done():
                self._session.cancel()

            notice_tasks = tuple(self._background_tasks)
            for task in notice_tasks:
                if not task.done():
                    task.cancel()
            owned_tasks = tuple(
                task for task in (active_run, *notice_tasks) if task is not None
            )
            if owned_tasks:
                await asyncio.gather(*owned_tasks, return_exceptions=True)
            self._background_tasks.clear()

            self._unbind_callbacks()

    async def send_model(self, model: BaseModel) -> None:
        """串行发送一个 canonical camelCase wire model。"""
        if self._closed:
            return
        async with self._send_lock:
            if not self._closed:
                await self._ws.send_text(model.model_dump_json(by_alias=True))

    async def handle_inbound_text(self, message_text: str) -> None:
        try:
            action = CLIENT_ACTION_ADAPTER.validate_json(message_text)
        except ValidationError:
            await self._send_protocol_error("客户端消息不符合 WebSocket action 契约")
            return
        await self._dispatch(action)

    async def handle_inbound_data(self, data: object) -> None:
        """供 ASGI 边界与单元测试共享同一个严格解码入口。"""
        try:
            action = CLIENT_ACTION_ADAPTER.validate_python(data)
        except ValidationError:
            await self._send_protocol_error("客户端消息不符合 WebSocket action 契约")
            return
        await self._dispatch(action)

    async def _on_confirm(self, message: str) -> bool:
        if self._closed:
            return False
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending_confirms[request_id] = future
        try:
            await self.send_model(
                ConfirmRequestEvent(request_id=request_id, message=message)
            )
            return await future
        finally:
            self._pending_confirms.pop(request_id, None)

    async def _on_plan_approval(self, plan: str) -> dict[str, Any]:
        if self._closed:
            return {"choice": "keep-planning"}
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending_plan_approvals[request_id] = future
        try:
            await self.send_model(
                PlanApprovalRequestEvent(request_id=request_id, plan=plan)
            )
            return await future
        finally:
            self._pending_plan_approvals.pop(request_id, None)

    def _on_notice(self, text: str, role: Literal["info", "error"]) -> None:
        if self._closed:
            return
        task = asyncio.create_task(self.send_model(NoticeEvent(text=text, role=role)))
        self._background_tasks.add(task)
        task.add_done_callback(self._consume_background_task)

    async def _dispatch(self, action: ClientAction) -> None:
        if isinstance(action, PromptAction):
            await self._handle_prompt(action.prompt)
        elif isinstance(action, SteerAction):
            await self._handle_queued_prompt(action.prompt, "steer")
        elif isinstance(action, FollowUpAction):
            await self._handle_queued_prompt(action.prompt, "follow_up")
        elif isinstance(action, ContinueAction):
            await self._handle_continue()
        elif isinstance(action, CancelAction):
            self._deny_pending_requests()
            self._session.cancel()
        elif isinstance(action, ConfirmResponseAction):
            confirm_future = self._pending_confirms.get(action.request_id)
            if confirm_future is not None and not confirm_future.done():
                confirm_future.set_result(action.approved)
        elif isinstance(action, PlanApprovalResponseAction):
            plan_future = self._pending_plan_approvals.get(action.request_id)
            if plan_future is not None and not plan_future.done():
                plan_future.set_result(
                    {"choice": action.choice, "feedback": action.feedback}
                )
        elif isinstance(action, CompactAction):
            await self._handle_compact()
        elif isinstance(action, CommandAction):
            await self._handle_command(action.command)

    async def _handle_prompt(self, prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt:
            await self._send_protocol_error("prompt 不能为空")
            return
        if self._run_in_progress():
            await self._send_protocol_error(
                "会话正在运行，请使用 steer 或 follow_up action"
            )
            return
        self._start_run(self._drive_prompt(prompt))

    async def _handle_queued_prompt(
        self,
        prompt: str,
        behavior: Literal["steer", "follow_up"],
    ) -> None:
        prompt = prompt.strip()
        if not prompt:
            await self._send_protocol_error("队列消息不能为空")
            return
        if not self._session.is_running:
            await self._send_protocol_error("会话未运行，无法写入运行队列")
            return
        async for event in self._session.prompt(
            prompt,
            streaming_behavior=behavior,
        ):
            await self.send_model(event)

    async def _handle_continue(self) -> None:
        if self._run_in_progress():
            await self._send_protocol_error("会话正在运行，无法继续")
            return
        self._start_run(self._drive_continue())

    async def _handle_compact(self) -> None:
        if self._run_in_progress():
            await self._send_protocol_error("会话正在运行，无法压缩")
            return
        try:
            await self._session.compact()
        except Exception as exc:
            await self.send_model(
                NoticeEvent(text=f"Compact failed: {exc}", role="error")
            )

    async def _handle_command(self, command: str) -> None:
        if self._run_in_progress():
            await self._send_protocol_error("会话运行中，无法执行命令")
            return
        command = command.strip()
        if not command.startswith("/"):
            await self._send_protocol_error("command 必须是 slash command")
            return

        result = self._session.handle_command(command)
        if not result.handled:
            await self._send_protocol_error(f"未知命令: {command}")
            return
        if result.plan_toggle_requested:
            self._session.toggle_plan_mode()
            await self.send_model(NoticeEvent(text="Plan mode toggled.", role="info"))
            return
        if result.message:
            await self.send_model(NoticeEvent(text=result.message, role="info"))
            return
        await self.send_model(
            NoticeEvent(text=f"Web 界面暂不支持命令: {command}", role="error")
        )

    def _start_run(self, run: AsyncIterator[BaseModel]) -> None:
        task = asyncio.create_task(self._drive_events(run))
        self._active_run_task = task
        task.add_done_callback(self._consume_active_run)

    async def _drive_prompt(self, text: str) -> AsyncIterator[BaseModel]:
        async for event in self._session.prompt(text):
            yield event

    async def _drive_continue(self) -> AsyncIterator[BaseModel]:
        async for event in self._session.continue_():
            yield event

    async def _drive_events(self, events: AsyncIterator[BaseModel]) -> None:
        try:
            async for event in events:
                await self.send_model(event)
        except Exception as exc:
            await self.send_model(
                ServerErrorEvent(message=str(exc) or type(exc).__name__)
            )

    def _run_in_progress(self) -> bool:
        task = self._active_run_task
        return self._session.is_running or (task is not None and not task.done())

    def _consume_active_run(self, task: asyncio.Task[None]) -> None:
        if self._active_run_task is task:
            self._active_run_task = None
        self._consume_task_result(task)

    def _consume_background_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        self._consume_task_result(task)

    @staticmethod
    def _consume_task_result(task: asyncio.Task[None]) -> None:
        with suppress(asyncio.CancelledError):
            task.exception()

    async def _send_protocol_error(self, message: str) -> None:
        await self.send_model(ProtocolErrorEvent(message=message))

    def _deny_pending_requests(self) -> None:
        for confirm_future in self._pending_confirms.values():
            if not confirm_future.done():
                confirm_future.set_result(False)
        self._pending_confirms.clear()

        for plan_future in self._pending_plan_approvals.values():
            if not plan_future.done():
                plan_future.set_result({"choice": "keep-planning"})
        self._pending_plan_approvals.clear()

    def _unbind_callbacks(self) -> None:
        if not self._bound:
            return
        self._session.set_confirm_fn(None)
        self._session.set_plan_approval_fn(None)
        self._session.set_notice_fn(None)
        self._bound = False


class WebsocketConnectionLease:
    """用对象身份保证一个 Session 同时只绑定一个浏览器连接。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._owner: SessionWebsocketBridge | None = None

    def acquire(self, owner: SessionWebsocketBridge) -> bool:
        with self._lock:
            if self._owner is not None:
                return False
            self._owner = owner
            return True

    def release(self, owner: SessionWebsocketBridge) -> None:
        with self._lock:
            if self._owner is owner:
                self._owner = None

    @property
    def owner(self) -> SessionWebsocketBridge | None:
        """当前持有租约的连接；lifespan 关闭时按 owner 顺序先收敛它。"""
        with self._lock:
            return self._owner
