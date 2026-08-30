"""统一工具执行入口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from ..core.cancellation import CancellationView
from .context import ToolContext
from .egress_guard import EgressConfiguration
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
        egress_configuration: EgressConfiguration | None = None,
    ) -> None:
        self.registry = registry
        self.context = context
        self.middleware = tuple(middleware)
        self._egress_configuration = egress_configuration

    def egress_hosts(self) -> list[str]:
        """返回 tooling 管理的 Egress 白名单，供应用端口读取。"""

        if self._egress_configuration is None:
            raise RuntimeError("Egress configuration is unavailable")
        return self._egress_configuration.configured_hosts()

    def configure_egress(self, allow_hosts: Sequence[str]) -> list[str]:
        """更新 Egress 配置并刷新当前 ToolRuntime 的白名单。"""

        if self._egress_configuration is None:
            raise RuntimeError("Egress configuration is unavailable")
        return self._egress_configuration.configure_hosts(allow_hosts)

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
