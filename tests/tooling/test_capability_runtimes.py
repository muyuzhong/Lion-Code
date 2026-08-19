from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lion_code.capabilities.skill.runtime import SkillRuntime
from lion_code.capabilities.subagent.runtime import SubagentExecutor
from lion_code.tooling.types import ToolResult
from lion_code.usage import UsageLedger


class _SkillExecutor:
    def __init__(self, result: ToolResult) -> None:
        self.execute_skill_fork = AsyncMock(return_value=result)


class _Child:
    def __init__(
        self, result: dict | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.run_once = AsyncMock(side_effect=self._run_once)
        self.close = AsyncMock()

    async def _run_once(self, _prompt: str) -> dict:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _Factory:
    def __init__(self, child: _Child) -> None:
        self.child = child
        self.agent_type: str | None = None
        self.skill_args: dict | None = None

    def create_for_agent_type(self, agent_type: str) -> _Child:
        self.agent_type = agent_type
        return self.child

    def create_for_skill(
        self, *, system_prompt: str, allowed_tools: list[str] | None
    ) -> _Child:
        self.skill_args = {
            "system_prompt": system_prompt,
            "allowed_tools": allowed_tools,
        }
        return self.child


@pytest.mark.asyncio
async def test_skill_runtime_handles_inline_and_unknown_skills() -> None:
    executor = _SkillExecutor(ToolResult(content="unused"))
    runtime = SkillRuntime(executor)  # type: ignore[arg-type]

    with patch(
        "lion_code.capabilities.skill.discovery.execute_skill",
        side_effect=[
            {"context": "inline", "prompt": "Use the inline instructions."},
            None,
        ],
    ):
        inline = await runtime({"skill_name": "inline"})
        unknown = await runtime({"skill_name": "missing"})

    assert (
        inline.content == '[Skill "inline" activated]\n\nUse the inline instructions.'
    )
    assert not inline.is_error
    assert unknown.content == "Unknown skill: missing"
    assert not unknown.is_error
    executor.execute_skill_fork.assert_not_awaited()


@pytest.mark.asyncio
async def test_skill_runtime_delegates_fork_to_subagent_executor() -> None:
    executor = _SkillExecutor(ToolResult(content="fork result"))
    runtime = SkillRuntime(executor)  # type: ignore[arg-type]
    skill = {
        "context": "fork",
        "prompt": "Skill system prompt",
        "allowed_tools": ["read_file"],
    }

    with patch("lion_code.capabilities.skill.discovery.execute_skill", return_value=skill):
        result = await runtime({"skill_name": "research", "args": "find the docs"})

    assert result.content == "fork result"
    executor.execute_skill_fork.assert_awaited_once_with(
        skill_name="research",
        prompt="Skill system prompt",
        allowed_tools=["read_file"],
        args="find the docs",
    )


@pytest.mark.asyncio
async def test_subagent_executor_success_merges_usage_status_and_closes() -> None:
    child = _Child({"text": "child result", "tokens": {"input": 3, "output": 5}})
    factory = _Factory(child)
    usage = UsageLedger()
    status: list[tuple[str, str, bool]] = []

    def record_status(agent_type: str, description: str, *, started: bool) -> None:
        status.append((agent_type, description, started))

    executor = SubagentExecutor(factory, usage, record_status)
    result = await executor(
        {"type": "explore", "description": "inspect", "prompt": "read"}
    )

    assert result.content == "child result"
    assert not result.is_error
    assert factory.agent_type == "explore"
    assert (usage.snapshot().input_tokens, usage.snapshot().output_tokens) == (3, 5)
    assert status == [("explore", "inspect", True), ("explore", "inspect", False)]
    child.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_subagent_executor_converts_errors_and_still_closes_child() -> None:
    child = _Child(error=RuntimeError("child failed"))
    factory = _Factory(child)
    usage = UsageLedger()
    status: list[bool] = []
    executor = SubagentExecutor(
        factory,
        usage,
        lambda _type, _description, *, started: status.append(started),
    )

    result = await executor({"type": "general", "description": "run", "prompt": "work"})

    assert result.content == "Sub-agent error: child failed"
    assert result.is_error
    assert usage.snapshot().input_tokens == 0
    assert status == [True, False]
    child.close.assert_awaited_once_with()
