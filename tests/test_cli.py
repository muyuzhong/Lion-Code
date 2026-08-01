"""CLI 入口的 TUI 单路径契约。"""

import sys
from unittest.mock import AsyncMock, patch

import pytest

from lion_code.__main__ import main, parse_args, run_repl
from lion_code.agent import Agent
from lion_code.project_identity import resolve_project_identity
from lion_code.session_memory import SessionMemory, SessionMemoryRepository


def test_legacy_tui_option_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["lion-code", "--legacy-tui"])

    with pytest.raises(SystemExit):
        parse_args()


def test_help_describes_default_tui_without_legacy_option(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["lion-code", "--help"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "启动 TUI" in output
    assert "Enable extended thinking for supported models" in output
    assert "--legacy-tui" not in output


@pytest.mark.asyncio
async def test_repl_routes_session_memory_commands_through_shared_intents(
    monkeypatch,
    tmp_path,
) -> None:
    from core.fakes import FakeProvider

    repository = SessionMemoryRepository(
        resolve_project_identity(),
        storage_dir=tmp_path / "session-memory",
    )
    with patch("lion_code.agent.create_provider", return_value=FakeProvider([])):
        agent = Agent(
            api_base="https://example.test/v1",
            api_key="test-key",
            custom_system_prompt="test",
            session_memory_repository=repository,
            terminal_output=False,
        )
    agent._mcp_initialized = True
    agent._session_memory = repository.save(
        SessionMemory(
            project_root=str(agent._project_identity.root),
            active_task="接入 REPL 命令",
            next_step="验证命令",
        )
    )
    agent.dream = AsyncMock(return_value="Dream 完成")
    inputs = iter((
        "/task",
        "/task switch 生成交接",
        "/handoff",
        "/session-memory",
        "/dream",
        "exit",
    ))
    monkeypatch.setattr("builtins.input", lambda: next(inputs))
    monkeypatch.setattr("lion_code.__main__.signal.signal", lambda *_args: None)

    await run_repl(agent)

    assert agent.session_memory is not None
    assert agent.session_memory.active_task == "生成交接"
    assert agent.session_memory.previous_handoff is not None
    agent.dream.assert_awaited_once()
