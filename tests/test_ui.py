"""REPL 终端渲染的最小 stdout 契约。"""

from lion_code import ui


def test_print_helpers_write_directly_to_stdout(capsys) -> None:
    ui.print_assistant_text("hello")
    ui.print_info("plain")
    ui.print_error("bad")

    output = capsys.readouterr().out
    assert "hello" in output
    assert "plain" in output
    assert "bad" in output
