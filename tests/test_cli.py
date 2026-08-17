"""CLI 入口的通用参数与帮助文本契约。"""

import sys
from argparse import Namespace
from unittest.mock import patch

import pytest

from lion_code.__main__ import _resolve_permission_mode, main, parse_args, run_repl
from lion_code.agent import Agent


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


def test_permission_mode_precedence_is_explicit() -> None:
    assert (
        _resolve_permission_mode(Namespace(yolo=True, accept_edits=True, dont_ask=True))
        == "bypassPermissions"
    )
    assert (
        _resolve_permission_mode(
            Namespace(yolo=False, accept_edits=True, dont_ask=True)
        )
        == "acceptEdits"
    )
    assert (
        _resolve_permission_mode(
            Namespace(yolo=False, accept_edits=False, dont_ask=True)
        )
        == "dontAsk"
    )
    assert (
        _resolve_permission_mode(
            Namespace(yolo=False, accept_edits=False, dont_ask=False)
        )
        == "default"
    )


@pytest.mark.asyncio
async def test_repl_routes_generic_command_through_application_session(
    monkeypatch,
) -> None:
    from core.fakes import FakeProvider

    with patch("lion_code.agent.create_provider", return_value=FakeProvider([])):
        agent = Agent(
            api_base="https://example.test/v1",
            api_key="test-key",
            custom_system_prompt="test",
            terminal_output=False,
        )

    inputs = iter(("/clear", "exit"))
    monkeypatch.setattr("builtins.input", lambda: next(inputs))
    monkeypatch.setattr("lion_code.__main__.signal.signal", lambda *_args: None)

    await run_repl(agent)
