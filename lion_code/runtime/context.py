"""上下文运行时：ContextManager / ContextCompactor / 模型限制缓存与压缩状态唯一 Owner。

ContextRuntime 拥有一次对话全部 context 派生决策的可变状态（effective_window、
compaction 标志、压缩任务句柄）。ProviderController 通过
``replace_context_compactor`` / ``invalidate_model_limit_cache`` 命令本 Owner；
AgentRuntime 在 run 编排中调用 prepare/compact 决策。
"""

from __future__ import annotations

import asyncio
import time

from ..context import (
    CompactionPlanView,
    CompactionRequest,
    ContextCompactor,
    ContextManager,
    ContextRuntimeState,
    ModelLimitsResolver,
    effective_window_tokens,
    fallback_model_limits,
    resolve_compaction_objective,
)
from ..core.messages import AgentMessage
from ..core.provider import ModelProvider
from ..usage import UsageLedger
from .execution import ExecutionControl


class ContextRuntime:
    """拥有 Context 派生服务与全部 compaction mutable state。"""

    def __init__(
        self,
        *,
        context_manager: ContextManager,
        context_compactor: ContextCompactor | None,
        model_limits_resolver: ModelLimitsResolver,
        usage: UsageLedger,
        execution: ExecutionControl,
        initial_effective_window: int,
        plan_view: CompactionPlanView | None = None,
    ) -> None:
        self._context_manager = context_manager
        self._context_compactor = context_compactor
        self._model_limits_resolver = model_limits_resolver
        self._usage = usage
        self._execution = execution
        self._plan_view = plan_view
        self.effective_window = initial_effective_window
        self._resolved_model_limits_for: tuple[int, str] | None = None
        self._compaction_required = False
        self._compaction_task: asyncio.Task[str] | None = None

    @property
    def context_manager(self) -> ContextManager:
        return self._context_manager

    @property
    def context_compactor(self) -> ContextCompactor | None:
        return self._context_compactor

    @property
    def resolved_model_limits_for(self) -> tuple[int, str] | None:
        return self._resolved_model_limits_for

    @property
    def compaction_required(self) -> bool:
        return self._compaction_required

    # ─── ProviderController 命令端口 ──────────────────────────

    def replace_context_compactor(self, compactor: ContextCompactor) -> None:
        """替换当前 Provider 对应的上下文压缩器。"""
        self._context_compactor = compactor

    def invalidate_model_limit_cache(self, model: str) -> None:
        """使模型限制重新解析，并清除旧模型的压缩决策。"""
        self._resolved_model_limits_for = None
        self._compaction_required = False
        self.effective_window = effective_window_tokens(fallback_model_limits(model))

    # ─── 模型限制解析（live provider/model 由调用方传入）──────

    async def resolve_model_limits(
        self,
        provider: ModelProvider,
        model: str,
    ) -> None:
        """按 live Provider/model 解析模型限制并更新 effective_window。"""

        key = (id(provider), model)
        if self._resolved_model_limits_for == key:
            return
        limits = await self._model_limits_resolver.resolve(provider, model)
        self.effective_window = effective_window_tokens(limits)
        self._resolved_model_limits_for = key

    # ─── 活跃上下文准备（Harness prepare_context 钩子）────────

    def runtime_state(self) -> ContextRuntimeState:
        """聚合 effective_window 与用量快照，作为投影策略输入。"""
        usage = self._usage.snapshot()
        return ContextRuntimeState(
            effective_window_tokens=self.effective_window,
            last_prompt_tokens=usage.last_prompt_tokens,
            last_model_call_at=usage.last_response_at,
            now=time.time(),
        )

    async def prepare_context(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        """通过 ContextManager 准备 Provider context，不改写 canonical history 或 JSONL。"""

        prepared = self._context_manager.prepare(messages, self.runtime_state())
        self._compaction_required = prepared.compaction_required
        return list(prepared.messages)

    # ─── 压缩决策与执行 ───────────────────────────────────────

    def should_compact_now(self) -> bool:
        return self._context_manager.should_compact(self.runtime_state())

    def evaluate_compaction_required(self) -> None:
        """run 结束后按当前窗口占用重估压缩标志。"""
        self._compaction_required = self.should_compact_now()

    async def summarize(
        self,
        messages: tuple[AgentMessage, ...],
        *,
        recent_context: tuple[AgentMessage, ...] = (),
        objective: str | None = None,
    ) -> str:
        """组装目标感知 request 并运行压缩器；任务句柄可被 abort 取消。"""

        if self._context_compactor is None:
            raise RuntimeError("No context compactor installed")
        if self._execution.cancelled:
            raise asyncio.CancelledError
        request = CompactionRequest(
            history=messages,
            recent_context=recent_context,
            objective=resolve_compaction_objective(
                requested_objective=objective,
                history=tuple(messages),
                recent_context=tuple(recent_context),
                plan_view=self._plan_view,
            ),
        )
        task = asyncio.create_task(self._context_compactor.summarize(request))
        self._compaction_task = task
        try:
            summary = await task
        finally:
            if self._compaction_task is task:
                self._compaction_task = None
        if self._execution.cancelled:
            raise asyncio.CancelledError
        return summary

    def cancel_pending_compaction(self) -> None:
        """取消可能正在运行的压缩任务（abort 路径）。"""
        if self._compaction_task is not None:
            self._compaction_task.cancel()

    def on_session_reset(self) -> None:
        """新会话/恢复会话时清除压缩决策。"""
        self._compaction_required = False

    def on_compacted(self) -> None:
        """压缩落盘完成后清除压缩决策。"""
        self._compaction_required = False
