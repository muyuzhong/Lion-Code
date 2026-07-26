"""Tests for drag-and-drop file insertion in the TUI prompt."""

import sys
from pathlib import Path

import pytest

# 上游用例基于 POSIX 终端的拖拽转义格式(反斜杠转义空格),与 Windows
# 路径分隔符冲突;Windows 下的拖拽归一化在阶段 3 接线 PromptInput 时处理。
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX terminal drop format"
)

from textual import events

from lion_code.tui.file_drop import normalize_dropped_paths


def _escaped(path: Path) -> str:
    """Render a path the way terminals do when a file is dropped."""
    return str(path).replace(" ", "\\ ")


class TestNormalizeDroppedPaths:
    def test_plain_absolute_path_passes_through(self, tmp_path: Path) -> None:
        file = tmp_path / "notes.txt"
        file.touch()

        assert normalize_dropped_paths(str(file)) == str(file)

    def test_escaped_spaces_are_unescaped_and_quoted(self, tmp_path: Path) -> None:
        file = tmp_path / "my file.png"
        file.touch()

        assert normalize_dropped_paths(_escaped(file)) == f'"{file}"'

    def test_bare_path_with_spaces_is_quoted(self, tmp_path: Path) -> None:
        file = tmp_path / "my file.png"
        file.touch()

        assert normalize_dropped_paths(str(file)) == f'"{file}"'

    def test_double_quoted_path_is_normalized(self, tmp_path: Path) -> None:
        file = tmp_path / "my file.png"
        file.touch()

        assert normalize_dropped_paths(f'"{file}"') == f'"{file}"'

    def test_multiple_dropped_files_join_with_spaces(self, tmp_path: Path) -> None:
        first = tmp_path / "first.txt"
        second = tmp_path / "second file.txt"
        first.touch()
        second.touch()

        dropped = f"{first} {_escaped(second)}"

        assert normalize_dropped_paths(dropped) == f'{first} "{second}"'

    def test_newline_separated_paths_join_with_spaces(self, tmp_path: Path) -> None:
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        first.touch()
        second.touch()

        assert normalize_dropped_paths(f"{first}\n{second}\n") == f"{first} {second}"

    def test_directory_path_is_accepted(self, tmp_path: Path) -> None:
        directory = tmp_path / "some dir"
        directory.mkdir()

        assert normalize_dropped_paths(_escaped(directory)) == f'"{directory}"'

    def test_file_uri_is_converted_to_local_path(self, tmp_path: Path) -> None:
        file = tmp_path / "my file.png"
        file.touch()
        uri = "file://" + str(file).replace(" ", "%20")

        assert normalize_dropped_paths(uri) == f'"{file}"'

    def test_missing_path_is_not_a_drop(self, tmp_path: Path) -> None:
        assert normalize_dropped_paths(str(tmp_path / "missing.txt")) is None

    def test_relative_path_is_not_a_drop(self) -> None:
        assert normalize_dropped_paths("pyproject.toml") is None

    def test_prose_is_not_a_drop(self) -> None:
        assert normalize_dropped_paths("please summarize /tmp") is None

    def test_blank_text_is_not_a_drop(self) -> None:
        assert normalize_dropped_paths("   \n ") is None

    def test_unbalanced_quotes_are_not_a_drop(self, tmp_path: Path) -> None:
        file = tmp_path / "notes.txt"
        file.touch()

        assert normalize_dropped_paths(f'"{file}') is None
