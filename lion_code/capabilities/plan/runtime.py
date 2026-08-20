"""Plan 模式状态与审批事务的唯一运行时 Owner。

Plan 是 Capability 层产品概念：本运行时只拥有 Plan 自身状态（激活状态与文件
路径）与审批流程，不再读写 Harness 的权限模式。Plan 期间的读写限制属于未来
``PlanRestrictedPolicy``（由 Composition / Profile 注入）的职责，PR4 起 Harness
Permission 只负责通用安全语义。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

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


@dataclass(frozen=True, slots=True)
class PlanToolOutcome:
    content: str
    terminate: bool = False


class PlanRuntime:
    """拥有 Plan 状态、审批与上下文重置命令。"""

    def __init__(
        self,
        host: PlanRuntimeHost,
        state: PlanState,
    ) -> None:
        self._host = host
        self._state = state
        self._approval_fn: PlanApprovalFn | None = None

    @property
    def is_active(self) -> bool:
        return self._state.status == "active"

    @property
    def file_path(self) -> Path | None:
        return self._state.file_path

    def set_approval_fn(self, fn: PlanApprovalFn | None) -> None:
        self._approval_fn = fn

    def toggle(self) -> str:
        if self.is_active:
            self._leave()
            self._host._emit_notice("Exited plan mode.")
            return "default"

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
            self._leave()
            self._host._emit_notice("Exited plan mode.")
            return PlanToolOutcome(
                f"Exited plan mode.\n\n## Your Plan:\n{plan_content}"
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

        # PR4：审批通过后不再切换权限模式。执行阶段的权限由未来的
        # PlanRestrictedPolicy / Composition 注入决定；clear-and-execute 的
        # 上下文清空增强同样依赖 Kernel 特判（PR3 已移除），保持降级。
        self._leave()
        self._host._emit_notice("Plan approved. Exited plan mode.")
        return PlanToolOutcome(
            f"User approved the plan.\n\n## Approved Plan:\n{plan_content}\n\n"
            "Proceed with implementation."
        )

    def reset_for_new_session(self) -> None:
        """为新会话重新生成激活 Plan 路径。"""

        if self.is_active:
            self._state.file_path = self._generate_file_path()

    def _enter(self) -> None:
        path = self._generate_file_path()
        self._state.status = "active"
        self._state.file_path = path

    def _leave(self) -> None:
        self._state.status = "inactive"
        self._state.file_path = None

    def _generate_file_path(self) -> Path:
        directory = Path.home() / ".claude" / "plans"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"plan-{self._host.session_id}.md"

    def _read_plan_content(self) -> str:
        path = self._state.file_path
        if path is None or not path.exists():
            return "(No plan file found)"
        return path.read_text()
