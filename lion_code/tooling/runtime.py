"""统一工具执行入口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from ..core.cancellation import CancellationView
from .audit import AuditResult, ExecutionEvent
from .context import ToolContext
from .middleware import ToolMiddleware, can_run_parallel
from .registry import ToolRegistry
from .types import JSONValue, ToolResult, ToolUpdateCallback


@dataclass(frozen=True, slots=True)
class _CombinedCancellationView:
    first: CancellationView
    second: CancellationView

    @property
    def cancelled(self) -> bool:
        return self.first.cancelled or self.second.cancelled

    def is_cancelled(self) -> bool:
        return self.cancelled


class ToolRuntime:
    """解析并执行注册工具，把异常转换为结构化错误结果。"""

    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolContext,
        middleware: Sequence[ToolMiddleware] = (),
    ) -> None:
        self.registry = registry
        self.context = context
        self.middleware = tuple(middleware)

    async def execute(
        self,
        *,
        tool_call_id: str,
        name: str,
        arguments: Mapping[str, JSONValue],
        on_update: ToolUpdateCallback | None = None,
        cancellation: CancellationView | None = None,
    ) -> ToolResult:
        try:
            tool = self.registry.resolve(name)
        except LookupError as exc:
            return ToolResult(content=str(exc), is_error=True)

        pre = [item for item in self.middleware if item.phase == "pre"]
        post = [item for item in self.middleware if item.phase == "post"]
        context = self._execution_context(cancellation)

        async def invoke(index: int) -> ToolResult:
            if index == len(pre):
                return await tool.execute(
                    context,
                    tool_call_id,
                    arguments,
                    on_update,
                )
            current = pre[index]
            return await current.handle(
                tool=tool,
                context=context,
                tool_call_id=tool_call_id,
                arguments=arguments,
                call_next=lambda: invoke(index + 1),
            )

        try:
            result = await invoke(0)
        except Exception as exc:
            # 异常转结果后同样要过 post 链：自定义工具抛出的
            # 异常消息可能携带 secret，绕过 sanitizer 即绕过窄腰
            result = ToolResult(
                content=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )

        try:
            for current in post:

                async def current_result(value=result) -> ToolResult:
                    return value

                result = await current.handle(
                    tool=tool,
                    context=context,
                    tool_call_id=tool_call_id,
                    arguments=arguments,
                    call_next=current_result,
                )
        except Exception as exc:
            return ToolResult(
                content=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )
        return result

    def rollback(self, snapshot_id: str, operation_summary: str) -> ToolResult:
        """恢复快照，并把恢复说明作为普通工具结果返回给模型。"""
        snapshot = self.context.workspace_snapshot
        rollback_details: dict[str, JSONValue] = {
            "snapshot_id": snapshot_id,
            "pre_restore_snapshot_id": None,
            "operation_summary": operation_summary,
            "restored": False,
        }
        if snapshot is None:
            return ToolResult(
                content="Workspace rollback is disabled.",
                is_error=True,
                details={"rollback": rollback_details},
            )

        error: str | None = None
        try:
            restored = snapshot.restore(snapshot_id)
        except Exception as exc:
            restored = None
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = (
                restored.error if restored is not None else "unknown restore failure"
            )

        if restored is not None:
            rollback_details["pre_restore_snapshot_id"] = (
                restored.pre_restore_snapshot_id
            )
            rollback_details["restored"] = restored.restored
        if restored is not None and restored.restored:
            content = "以下操作结果已被撤销，请基于当前 workspace 重新判断"
            is_error = False
            audit_result: AuditResult = "rolled_back"
        else:
            content = f"Rollback failed: {error or 'unknown restore failure'}"
            is_error = True
            audit_result = "failed"

        if self.context.audit_log is not None:
            self.context.audit_log.append(
                ExecutionEvent(
                    tool="rollback",
                    command_or_args=operation_summary,
                    snapshot_id=snapshot_id,
                    result=audit_result,
                )
            )
        return ToolResult(
            content=content,
            is_error=is_error,
            details={"rollback": rollback_details},
        )

    def _execution_context(
        self,
        cancellation: CancellationView | None,
    ) -> ToolContext:
        if cancellation is None or cancellation is self.context.cancellation:
            return self.context
        return replace(
            self.context,
            cancellation=_CombinedCancellationView(
                self.context.cancellation,
                cancellation,
            ),
        )

    def can_run_parallel(self, name: str) -> bool:
        """按 Registry 中的 Capability 判断工具是否可并行。"""
        try:
            return can_run_parallel(self.registry.resolve(name))
        except LookupError:
            return False
