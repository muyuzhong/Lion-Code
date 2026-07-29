"""CLI 入口的 TUI 单路径契约。"""

import sys

import pytest

from lion_code.__main__ import main, parse_args


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
    assert "--legacy-tui" not in output
