"""Plan 模式状态与跨层事务的唯一运行时 Owner。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .permission_state import PermissionController, PermissionMode

PlanStatus = Literal["inactive", "active"]
PlanApprovalFn = Callable[[str], Awaitable[dict[str, Any]]]


class PlanView(Protocol):
    """供工具和提示词层读取的实时 Plan 投影。"""

    @property
    def is_active(self) -> bool: ...

    @property
    def file_path(self) -> Path | None: ...


class PlanRuntimeHost(Protocol):
    """Plan 通知与路径生成所需的最窄宿主端口。"""

    @property
    def session_id(self) -> str: ...

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None: ...


@dataclass(slots=True)
class PlanState:
    status: PlanStatus = "inactive"
    file_path: Path | None = None
    previous_permission_mode: PermissionMode | None = None


@dataclass(frozen=True, slots=True)
class PlanToolOutcome:
    content: str
    terminate: bool = False


class PlanRuntime:
    """拥有 Plan 状态、权限事务、审批和上下文重置命令。"""

    def __init__(
        self,
        host: PlanRuntimeHost,
        permission: PermissionController,
        state: PlanState,
    ) -> None:
        self._host = host
        self._permission = permission
        self._state = state
        self._approval_fn: PlanApprovalFn | None = None

    @property
    def is_active(self) -> bool:
        return self._state.status == "active"

    @property
    def file_path(self) -> Path | None:
        return self._state.file_path

    def initialize(self) -> None:
        """初始权限为 Plan 时建立激活事务。"""

        if self._permission.mode != "plan":
            return
        path = self._generate_file_path()
        self._state.status = "active"
        self._state.file_path = path
        self._state.previous_permission_mode = None

    def set_approval_fn(self, fn: PlanApprovalFn | None) -> None:
        self._approval_fn = fn

    def toggle(self) -> PermissionMode:
        if self.is_active:
            target_mode = self._state.previous_permission_mode or "default"
            self._leave(target_mode)
            self._host._emit_notice(f"Exited plan mode → {self._permission.mode} mode")
            return self._permission.mode

        self._enter()
        self._host._emit_notice(
            f"Entered plan mode. Plan file: {self._state.file_path}"
        )
        return "plan"

    def enter(self) -> PlanToolOutcome:
        if self.is_active:
            return PlanToolOutcome("Already in plan mode.")

        self._enter()
        path = self._state.file_path
        self._host._emit_notice(f"Entered plan mode (read-only). Plan file: {path}")
        return PlanToolOutcome(
            "Entered plan mode. You are now in read-only mode.\n\n"
            f"Your plan file: {path}\n"
            "Write your plan to this file. This is the only file you can edit.\n\n"
            "When your plan is complete, call exit_plan_mode."
        )

    async def exit(self) -> PlanToolOutcome:
        if not self.is_active:
            return PlanToolOutcome("Not in plan mode.")

        plan_content = self._read_plan_content()
        if self._approval_fn is None:
            restore_mode = self._state.previous_permission_mode or "default"
            self._leave(restore_mode)
            self._host._emit_notice(
                f"Exited plan mode. Restored to {self._permission.mode} mode."
            )
            return PlanToolOutcome(
                "Exited plan mode. Permission mode restored to: "
                f"{self._permission.mode}\n\n## Your Plan:\n{plan_content}"
            )

        result = await self._approval_fn(plan_content)
        choice = result.get("choice", "manual-execute")
        if choice == "keep-planning":
            feedback = result.get("feedback") or "Please revise the plan."
            return PlanToolOutcome(
                "User rejected the plan and wants to keep planning.\n\n"
                f"User feedback: {feedback}\n\n"
                "Please revise your plan based on this feedback. When done, "
                "call exit_plan_mode again."
            )

        # clear-and-execute 的上下文清空增强（清空 + 自动 continue）依赖 Kernel
        # 对 Plan 的特判，PR3 已移除；迁移分支暂时降级为 execute 的事务。
        target_mode: PermissionMode = (
            "acceptEdits"
            if choice in {"execute", "clear-and-execute"}
            else self._state.previous_permission_mode or "default"
        )
        self._leave(target_mode)

        self._host._emit_notice(f"Plan approved. Executing in {target_mode} mode.")
        return PlanToolOutcome(
            f"User approved the plan. Permission mode: {target_mode}\n\n"
            f"## Approved Plan:\n{plan_content}\n\nProceed with implementation."
        )

    def reset_for_new_session(self) -> None:
        """为新会话重新生成激活 Plan 路径。"""

        if self.is_active:
            self._state.file_path = self._generate_file_path()

    def _enter(self) -> None:
        path = self._generate_file_path()
        previous_mode = self._permission.mode
        self._permission.set_mode("plan")
        self._state.status = "active"
        self._state.file_path = path
        self._state.previous_permission_mode = previous_mode

    def _leave(self, target_mode: PermissionMode) -> None:
        self._permission.set_mode(target_mode)
        self._state.status = "inactive"
        self._state.file_path = None
        self._state.previous_permission_mode = None

    def _generate_file_path(self) -> Path:
        directory = Path.home() / ".claude" / "plans"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"plan-{self._host.session_id}.md"

    def _read_plan_content(self) -> str:
        path = self._state.file_path
        if path is None or not path.exists():
            return "(No plan file found)"
        return path.read_text()
