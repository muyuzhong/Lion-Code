"""由 Agent 组合层持有的受限 Dream 子 Agent 适配器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from .dream import (
    DREAM_MAX_TURNS,
    DREAM_READ_TOOLS,
    DREAM_SYSTEM_PROMPT,
    DreamAgentResult,
    DreamContext,
    validate_dream_read_input,
)
from .subagent_factory import ChildAgentConfig
from .tooling import ToolEnvironment, ToolRegistry
from .tooling.context import ToolContext
from .tooling.selection import ToolSelectionPolicy, select_tools


class RestrictedDreamAgentFactory:
    """构造只含三个只读工具、禁用 MCP 和嵌套 Agent 的 Dream 子运行时。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        environment: ToolEnvironment,
        child_config: Callable[[], ChildAgentConfig],
    ) -> None:
        self._registry = registry
        self._environment = environment
        self._child_config = child_config

    def create(self, context: DreamContext) -> RestrictedDreamAgent:
        from .agent import Agent

        config = self._child_config()
        child_registry = select_tools(
            self._registry,
            ToolSelectionPolicy(
                allowed_names=frozenset(DREAM_READ_TOOLS),
                require_read_only=True,
            ),
        )
        read_roots = (context.project_root.resolve(), context.memory_dir.resolve())

        class DreamChild(Agent):
            tool_context: ToolContext

            def __init__(self) -> None:
                super().__init__(
                    model=config.model,
                    api_key=config.api_key,
                    api_base=config.api_base,
                    anthropic_base_url=config.anthropic_base_url,
                    terminal_output=config.terminal_output,
                    custom_system_prompt=DREAM_SYSTEM_PROMPT,
                    tool_registry=child_registry,
                    tool_environment=self_environment.child_view(),
                    is_sub_agent=True,
                    permission_mode="bypassPermissions",
                    max_turns=DREAM_MAX_TURNS,
                    mcp_enabled=False,
                )
                # 项目 Hook 可能间接启动 Shell，Dream 必须完全禁用它。
                self._pre_tool_use_hooks.clear()
                self.tool_context.hooks.clear()

            async def _execute_tool_call(
                self,
                name: str,
                inp: dict[Any, Any],
                tool_call_id: str = "",
            ) -> str:
                safe_input = validate_dream_read_input(
                    name,
                    cast(Mapping[str, Any], inp),
                    read_roots,
                )
                if safe_input is None:
                    return (
                        "Action denied: Dream Agent is read-only and restricted "
                        "to project Memory and code."
                    )
                return await super()._execute_tool_call(name, safe_input, tool_call_id)

        self_environment = self._environment
        return RestrictedDreamAgent(DreamChild(), read_roots)


class RestrictedDreamAgent:
    """把 concrete Agent 返回值投影成 Dream domain 的 typed result。"""

    def __init__(self, child: Any, read_roots: tuple[Path, ...]) -> None:
        self._child = child
        self._read_roots = read_roots

    def safe_read_input(
        self,
        name: str,
        inp: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """供安全测试验证与执行路径相同的路径策略。"""

        return validate_dream_read_input(name, inp, self._read_roots)

    async def run_once(self, prompt: str) -> DreamAgentResult:
        result = await self._child.run_once(prompt)
        tokens = result["tokens"]
        return DreamAgentResult(
            text=str(result.get("text") or ""),
            input_tokens=int(tokens["input"]),
            output_tokens=int(tokens["output"]),
        )

    async def close(self) -> None:
        await self._child.close()
