"""Tests for drag-and-drop file insertion in the TUI prompt."""

from pathlib import Path

import pytest

from lion_code.tui.file_drop import normalize_dropped_paths


def _escaped(path: Path) -> str:
    """Render a path the way POSIX terminals do when a file is dropped."""
    return str(path).replace(" ", "\\ ")


class TestNormalizeDroppedPaths:
    def test_plain_absolute_path_passes_through(self, tmp_path: Path) -> None:
        file = tmp_path / "notes.txt"
        file.touch()

        assert normalize_dropped_paths(str(file)) == str(file)

    def test_escaped_spaces_are_unescaped_and_quoted(self, tmp_path: Path) -> None:
        if Path("C:/").is_absolute():
            pytest.skip("POSIX terminal escape format")
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

        dropped = f'{first} "{second}"'

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

        dropped = str(directory) if Path("C:/").is_absolute() else _escaped(directory)

        assert normalize_dropped_paths(dropped) == f'"{directory}"'

    def test_file_uri_is_converted_to_local_path(self, tmp_path: Path) -> None:
        file = tmp_path / "my file.png"
        file.touch()

        assert normalize_dropped_paths(file.as_uri()) == f'"{file}"'

    def test_windows_quoted_multiple_paths_preserve_separators(self, tmp_path: Path) -> None:
        if not Path("C:/").is_absolute():
            pytest.skip("Windows terminal drop format")
        first = tmp_path / "first file.txt"
        second = tmp_path / "second.txt"
        first.touch()
        second.touch()

        dropped = f'"{first}" "{second}"'

        assert normalize_dropped_paths(dropped) == f'"{first}" {second}'

    def test_windows_unquoted_multiple_paths_use_non_posix_parsing(self, tmp_path: Path) -> None:
        if not Path("C:/").is_absolute():
            pytest.skip("Windows terminal drop format")
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        first.touch()
        second.touch()

        assert normalize_dropped_paths(f"{first} {second}") == f"{first} {second}"

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
