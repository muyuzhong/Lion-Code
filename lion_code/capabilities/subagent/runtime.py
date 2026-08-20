"""子 Agent 与 Skill fork 的独立执行生命周期。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from ...tooling.types import JSONValue, ToolResult
from ...usage import UsageLedger


class SubagentStatusCallback(Protocol):
    """报告子执行开始与结束的窄回调。"""

    def __call__(
        self,
        agent_type: str,
        description: str,
        *,
        started: bool,
    ) -> None: ...


class _ChildRuntime(Protocol):
    """子运行时需要的最小执行与释放接口。"""

    async def run_once(self, prompt: str) -> Mapping[str, Any]: ...

    async def close(self) -> None: ...


class _SubagentFactory(Protocol):
    """构造子运行时所需的最小工厂接口。"""

    def create_for_agent_type(self, agent_type: str) -> _ChildRuntime: ...

    def create_for_skill(
        self,
        *,
        system_prompt: str,
        allowed_tools: list[str] | None,
    ) -> _ChildRuntime: ...


class SubagentExecutor:
    """拥有子执行的状态展示、用量合并、错误转换与释放边界。

    ``SubagentFactory`` 只负责构造子实例；本类统一承接普通 SubAgent 和
    Skill fork 的运行生命周期，避免两个工具路径产生不同的资源与计费语义。
    """

    def __init__(
        self,
        factory: _SubagentFactory,
        usage: UsageLedger,
        status_callback: SubagentStatusCallback | None = None,
    ) -> None:
        self._factory = factory
        self._usage = usage
        self._status_callback = status_callback or self._ignore_status

    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        """执行 ``agent`` 工具传入的一个子任务。"""

        agent_type = _string_argument(arguments, "type", "general")
        description = _string_argument(
            arguments,
            "description",
            "sub-agent task",
        )
        prompt = _string_argument(arguments, "prompt", "")
        return await self.execute(
            agent_type=agent_type,
            description=description,
            prompt=prompt,
        )

    async def execute(
        self,
        *,
        agent_type: str,
        description: str,
        prompt: str,
    ) -> ToolResult:
        """按 Agent 类型构造并执行一个子任务。"""

        return await self._run_child(
            agent_type=agent_type,
            description=description,
            prompt=prompt,
            create=lambda: self._factory.create_for_agent_type(agent_type),
            error_prefix="Sub-agent error",
            empty_output="(Sub-agent produced no output)",
        )

    async def execute_skill_fork(
        self,
        *,
        skill_name: str,
        prompt: str,
        allowed_tools: list[str] | None,
        args: str,
    ) -> ToolResult:
        """按 Skill 的工具范围构造并执行一个 fork 子任务。"""

        return await self._run_child(
            agent_type="skill-fork",
            description=skill_name,
            prompt=args or "Execute this skill task.",
            create=lambda: self._factory.create_for_skill(
                system_prompt=prompt,
                allowed_tools=allowed_tools,
            ),
            error_prefix="Skill fork error",
            empty_output="(Skill produced no output)",
        )

    async def _run_child(
        self,
        *,
        agent_type: str,
        description: str,
        prompt: str,
        create: Callable[[], _ChildRuntime],
        error_prefix: str,
        empty_output: str,
    ) -> ToolResult:
        self._status_callback(agent_type, description, started=True)
        child: _ChildRuntime | None = None
        try:
            try:
                child = create()
                result = await child.run_once(prompt)
                tokens = result["tokens"]
                self._usage.record_child_usage(
                    int(tokens["input"]),
                    int(tokens["output"]),
                )
            except Exception as exc:
                return ToolResult(
                    content=f"{error_prefix}: {exc}",
                    is_error=True,
                )

            text = result.get("text") or empty_output
            return ToolResult(content=str(text))
        finally:
            try:
                self._status_callback(agent_type, description, started=False)
            finally:
                if child is not None:
                    await child.close()

    @staticmethod
    def _ignore_status(
        agent_type: str,
        description: str,
        *,
        started: bool,
    ) -> None:
        del agent_type, description, started


def _string_argument(
    arguments: Mapping[str, JSONValue],
    name: str,
    default: str,
) -> str:
    value = arguments.get(name, default)
    return value if isinstance(value, str) else str(value)
