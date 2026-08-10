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
    """工具层可读取的实时 Plan 投影，不暴露命令或可写状态。"""

    @property
    def is_active(self) -> bool: ...

    @property
    def file_path(self) -> Path | None: ...


class PlanRuntimeHost(Protocol):
    """Plan 事务更新提示词与通知所需的最窄宿主端口。"""

    _base_system_prompt: str
    _system_prompt: str

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
    pending_context_reset: str | None = None


@dataclass(frozen=True, slots=True)
class PlanToolOutcome:
    content: str
    terminate: bool = False


class PlanRuntime:
    """拥有 Plan 状态，并原子协调权限、提示词、审批与上下文重置。"""

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

    @property
    def pending_context_reset(self) -> str | None:
        return self._state.pending_context_reset

    def initialize(self) -> None:
        """在初始权限为 Plan 时建立状态；其他模式保持 inactive。"""

        if self._permission.mode != "plan":
            self.refresh_prompt()
            return
        path = self._generate_file_path()
        self._state.status = "active"
        self._state.file_path = path
        self._state.previous_permission_mode = None
        self._state.pending_context_reset = None
        self.refresh_prompt()

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

        target_mode: PermissionMode = (
            "acceptEdits"
            if choice in {"execute", "clear-and-execute"}
            else self._state.previous_permission_mode or "default"
        )
        saved_plan_path = self._state.file_path
        pending_reset = None
        if choice == "clear-and-execute":
            pending_reset = (
                f"Approved plan:\n{plan_content}\n\nProceed with implementation."
            )
        self._leave(target_mode, pending_context_reset=pending_reset)

        if choice == "clear-and-execute":
            self._host._emit_notice(
                f"Plan approved. Context cleared, executing in {target_mode} mode."
            )
            return PlanToolOutcome(
                "User approved the plan. Context was cleared. Permission mode: "
                f"{target_mode}\n\nPlan file: {saved_plan_path}\n\n"
                f"## Approved Plan:\n{plan_content}\n\nProceed with implementation.",
                terminate=True,
            )

        self._host._emit_notice(f"Plan approved. Executing in {target_mode} mode.")
        return PlanToolOutcome(
            f"User approved the plan. Permission mode: {target_mode}\n\n"
            f"## Approved Plan:\n{plan_content}\n\nProceed with implementation."
        )

    def reset_for_new_session(self) -> None:
        """清理旧 pending；active Plan 为新 Session 重建 path 与 prompt。"""

        path = self._generate_file_path() if self.is_active else None
        self._state.pending_context_reset = None
        if path is not None:
            self._state.file_path = path
        self.refresh_prompt()

    def reset_after_restore(self) -> None:
        """恢复 JSONL 时只撤销未完成 reset，不改当前 Plan path。"""

        self._state.pending_context_reset = None

    def complete_context_reset(self) -> None:
        """仅由 Core 上下文持久化、回放和 reset 全部成功后确认完成。"""

        self._state.pending_context_reset = None

    def refresh_prompt(self) -> None:
        prompt = self._host._base_system_prompt
        if self.is_active:
            prompt += self._build_prompt()
        self._host._system_prompt = prompt

    def _enter(self) -> None:
        path = self._generate_file_path()
        previous_mode = self._permission.mode
        self._permission.set_mode("plan")
        self._state.status = "active"
        self._state.file_path = path
        self._state.previous_permission_mode = previous_mode
        self._state.pending_context_reset = None
        self.refresh_prompt()

    def _leave(
        self,
        target_mode: PermissionMode,
        *,
        pending_context_reset: str | None = None,
    ) -> None:
        self._permission.set_mode(target_mode)
        self._state.status = "inactive"
        self._state.file_path = None
        self._state.previous_permission_mode = None
        self._state.pending_context_reset = pending_context_reset
        self.refresh_prompt()

    def _generate_file_path(self) -> Path:
        directory = Path.home() / ".claude" / "plans"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"plan-{self._host.session_id}.md"

    def _build_prompt(self) -> str:
        return f"""

# Plan Mode Active

Plan mode is active. You MUST NOT make any edits (except the plan file below), run non-readonly tools, or make any changes to the system.

## Plan File: {self._state.file_path}
Write your plan incrementally to this file using write_file or edit_file. This is the ONLY file you are allowed to edit.

## Workflow
1. **Explore**: Read code to understand the task. Use read_file, list_files, grep_search.
2. **Design**: Design your implementation approach. Use the agent tool with type="plan" if the task is complex.
3. **Write Plan**: Write a structured plan to the plan file including:
   - **Context**: Why this change is needed
   - **Steps**: Implementation steps with critical file paths
   - **Verification**: How to test the changes
4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

IMPORTANT: When your plan is complete, you MUST call exit_plan_mode. Do NOT ask the user to approve — exit_plan_mode handles that."""

    def _read_plan_content(self) -> str:
        path = self._state.file_path
        if path is None or not path.exists():
            return "(No plan file found)"
        return path.read_text()
