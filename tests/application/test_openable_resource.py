"""WorkPanel 资源投影与读取边界测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lion_code.application.openable_resource import (
    OPENABLE_RESOURCE_MAX_BYTES,
    openable_resource_for_tool,
    read_openable_resource,
)


def test_projects_only_persisted_path_or_known_file_tool() -> None:
    persisted = openable_resource_for_tool(
        "run_shell",
        {"command": "cat secret.txt"},
        {"persisted_path": "C:/results/output.txt", "original_bytes": 42},
    )
    assert persisted is not None
    assert persisted.path == "C:/results/output.txt"
    assert persisted.expected_size == 42

    file_result = openable_resource_for_tool(
        "read_file", {"file_path": "notes.md"}, None
    )
    assert file_result is not None
    assert file_result.path == "notes.md"

    assert (
        openable_resource_for_tool("run_shell", {"command": "cat notes.md"}, None)
        is None
    )
    assert openable_resource_for_tool("list_files", {"path": "notes.md"}, None) is None


def test_reads_workspace_utf8_and_detects_format(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(b"# Hello\n")

    resource = read_openable_resource(tmp_path, "README.md")

    assert resource.status == "ready"
    assert resource.format == "markdown"
    assert resource.content == "# Hello\n"
    assert resource.size == len(b"# Hello\n")
    assert resource.modified_at_ns is not None


def test_rejects_outside_directory_and_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    assert read_openable_resource(tmp_path, str(outside)).status == "outside_workspace"

    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前 Windows 测试环境不允许创建符号链接")
    assert read_openable_resource(tmp_path, "escape.txt").status == "outside_workspace"


def test_rejects_invalid_path_without_raising(tmp_path: Path) -> None:
    resource = read_openable_resource(tmp_path, "\x00invalid")

    assert resource.status in {"outside_workspace", "unreadable"}
    assert resource.content is None


def test_returns_bounded_structured_failures_without_content(tmp_path: Path) -> None:
    missing = read_openable_resource(tmp_path, "missing.txt")
    assert missing.status == "missing"
    assert missing.content is None

    directory = tmp_path / "directory"
    directory.mkdir()
    assert read_openable_resource(tmp_path, "directory").status == "not_file"

    large = tmp_path / "large.txt"
    large.write_bytes(b"x" * (OPENABLE_RESOURCE_MAX_BYTES + 1))
    too_large = read_openable_resource(tmp_path, "large.txt")
    assert too_large.status == "too_large"
    assert too_large.content is None

    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"header\x00payload")
    assert read_openable_resource(tmp_path, "binary.bin").status == "binary"

    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff")
    assert read_openable_resource(tmp_path, "invalid.txt").status == "encoding_error"


def test_detects_changed_expected_attributes(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("one", encoding="utf-8")
    first = read_openable_resource(tmp_path, "file.txt")
    assert first.status == "ready"
    assert first.size is not None
    assert first.modified_at_ns is not None

    path.write_bytes(b"changed")
    changed = read_openable_resource(
        tmp_path,
        "file.txt",
        expected_size=first.size,
        expected_mtime_ns=first.modified_at_ns,
    )

    assert changed.status == "changed"
    assert changed.content is None
