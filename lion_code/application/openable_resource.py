"""桌面 WorkPanel 的受限只读资源投影与读取。"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OPENABLE_RESOURCE_MAX_BYTES = 256 * 1024
OPENABLE_RESULT_ROOT = Path.home() / ".lion-code" / "tool-results"
OPENABLE_FILE_TOOLS = frozenset({"read_file", "write_file", "edit_file"})

type OpenableResourceStatus = Literal[
    "ready",
    "missing",
    "outside_workspace",
    "not_file",
    "too_large",
    "binary",
    "encoding_error",
    "changed",
    "unreadable",
]
type OpenableResourceFormat = Literal["text", "markdown", "diff"]


@dataclass(frozen=True, slots=True)
class OpenableResourceRef:
    """可传给桌面读取接口的最小资源引用。"""

    path: str
    expected_size: int | None = None


@dataclass(frozen=True, slots=True)
class OpenableResource:
    """一次有界读取的展示结果；非 ready 状态不携带内容。"""

    status: OpenableResourceStatus
    path: str
    name: str
    format: OpenableResourceFormat
    size: int | None
    modified_at_ns: int | None
    content: str | None
    message: str | None = None


def openable_resource_for_tool(
    tool_name: str,
    args: object,
    details: object,
) -> OpenableResourceRef | None:
    """从成功工具的安全字段投影最小资源引用。

    只接受 ResultStore 写入的 ``persisted_path``，或三个内置文件工具的
    ``file_path``。未知工具、Shell 命令和搜索字段不会被猜测为文件路径。
    """
    detail_values = _mapping(details)
    if detail_values is not None:
        persisted_path = detail_values.get("persisted_path")
        if isinstance(persisted_path, str) and persisted_path.strip():
            return OpenableResourceRef(
                path=persisted_path,
                expected_size=_non_negative_int(detail_values.get("original_bytes")),
            )

    if tool_name not in OPENABLE_FILE_TOOLS:
        return None
    argument_values = _mapping(args)
    if argument_values is None:
        return None
    file_path = argument_values.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    return OpenableResourceRef(path=file_path)


def read_openable_resource(
    cwd: Path,
    raw_path: str,
    *,
    expected_size: int | None = None,
    expected_mtime_ns: int | None = None,
) -> OpenableResource:
    """在工作区或默认结果根内读取一个有界 UTF-8 文本资源。

    每次调用都重新 resolve/stat/read；读取前后属性变化时丢弃内容，避免把
    竞态中的半份文件伪装成稳定快照。路径越界、二进制和解码失败均只返回
    结构化状态。
    """
    roots = _resolve_resource_paths(cwd, raw_path)
    if roots is None:
        return _resource(
            "outside_workspace",
            raw_path,
            _resource_name(raw_path),
            size=None,
            modified_at_ns=None,
            message="无法验证资源路径",
        )
    workspace_root, result_root, resolved = roots

    if not _is_within(resolved, workspace_root) and not _is_within(
        resolved, result_root
    ):
        return _resource(
            "outside_workspace",
            raw_path,
            _resource_name(raw_path),
            size=None,
            modified_at_ns=None,
            message="资源不在当前工作区或工具结果目录内",
        )

    return _read_resource(
        resolved,
        workspace_root,
        result_root,
        raw_path,
        expected_size=expected_size,
        expected_mtime_ns=expected_mtime_ns,
    )


def _resolve_resource_paths(cwd: Path, raw_path: str) -> tuple[Path, Path, Path] | None:
    try:
        candidate = Path(raw_path)
        workspace_root = cwd.resolve(strict=False)
        result_root = OPENABLE_RESULT_ROOT.resolve(strict=False)
        resolved = (candidate if candidate.is_absolute() else cwd / candidate).resolve(
            strict=False
        )
    except (OSError, ValueError):
        return None
    return workspace_root, result_root, resolved


def _read_resource(
    resolved: Path,
    workspace_root: Path,
    result_root: Path,
    raw_path: str,
    *,
    expected_size: int | None,
    expected_mtime_ns: int | None,
) -> OpenableResource:
    name = resolved.name or _resource_name(raw_path)
    resource_format = _format_for_path(resolved)
    before = _stat_resource(resolved, name, resource_format)
    if isinstance(before, OpenableResource):
        return before

    verified = _verify_resource_path(
        resolved,
        workspace_root,
        result_root,
        name,
        resource_format,
        before,
    )
    if isinstance(verified, OpenableResource):
        return verified
    resolved = verified
    name = resolved.name or name
    resource_format = _format_for_path(resolved)

    if _changed(before.st_size, before.st_mtime_ns, expected_size, expected_mtime_ns):
        return _resource(
            "changed",
            str(resolved),
            name,
            size=before.st_size,
            modified_at_ns=before.st_mtime_ns,
            format=resource_format,
            message="资源在上次读取后发生变化",
        )
    if before.st_size > OPENABLE_RESOURCE_MAX_BYTES:
        return _resource(
            "too_large",
            str(resolved),
            name,
            size=before.st_size,
            modified_at_ns=before.st_mtime_ns,
            format=resource_format,
            message=f"资源超过 {OPENABLE_RESOURCE_MAX_BYTES // 1024} KiB 读取上限",
        )

    return _read_resource_data(
        resolved,
        workspace_root,
        result_root,
        name,
        resource_format,
        before,
    )


def _stat_resource(
    resolved: Path,
    name: str,
    resource_format: OpenableResourceFormat,
) -> os.stat_result | OpenableResource:
    try:
        before = resolved.stat()
    except FileNotFoundError:
        return _resource(
            "missing",
            str(resolved),
            name,
            size=None,
            modified_at_ns=None,
            format=resource_format,
            message="资源不存在",
        )
    except (OSError, ValueError):
        return _resource(
            "unreadable",
            str(resolved),
            name,
            size=None,
            modified_at_ns=None,
            format=resource_format,
            message="资源无法读取",
        )

    if not stat.S_ISREG(before.st_mode):
        return _resource(
            "not_file",
            str(resolved),
            name,
            size=before.st_size,
            modified_at_ns=before.st_mtime_ns,
            format=resource_format,
            message="资源不是普通文件",
        )
    return before


def _verify_resource_path(
    resolved: Path,
    workspace_root: Path,
    result_root: Path,
    name: str,
    resource_format: OpenableResourceFormat,
    before: os.stat_result,
) -> Path | OpenableResource:
    try:
        verified = resolved.resolve(strict=True)
    except (FileNotFoundError, OSError, ValueError):
        return _resource(
            "missing",
            str(resolved),
            name,
            size=None,
            modified_at_ns=None,
            format=resource_format,
            message="资源在读取前被删除",
        )
    if not _is_within(verified, workspace_root) and not _is_within(
        verified, result_root
    ):
        return _resource(
            "outside_workspace",
            str(resolved),
            name,
            size=before.st_size,
            modified_at_ns=before.st_mtime_ns,
            format=resource_format,
            message="资源符号链接指向不允许的路径",
        )
    return verified


def _read_resource_data(
    resolved: Path,
    workspace_root: Path,
    result_root: Path,
    name: str,
    resource_format: OpenableResourceFormat,
    before: os.stat_result,
) -> OpenableResource:
    snapshot = _read_resource_bytes(resolved, name, resource_format, before)
    if isinstance(snapshot, OpenableResource):
        return snapshot
    data, after = snapshot

    after_resolved = _verify_after_read(
        resolved,
        workspace_root,
        result_root,
        name,
        resource_format,
        after,
    )
    if isinstance(after_resolved, OpenableResource):
        return after_resolved
    if (
        not stat.S_ISREG(after.st_mode)
        or after_resolved != resolved
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        return _resource(
            "changed",
            str(resolved),
            name,
            size=after.st_size,
            modified_at_ns=after.st_mtime_ns,
            format=resource_format,
            message="资源在读取过程中发生变化",
        )
    if len(data) > OPENABLE_RESOURCE_MAX_BYTES:
        return _resource(
            "too_large",
            str(resolved),
            name,
            size=after.st_size,
            modified_at_ns=after.st_mtime_ns,
            format=resource_format,
            message=f"资源超过 {OPENABLE_RESOURCE_MAX_BYTES // 1024} KiB 读取上限",
        )
    if b"\x00" in data:
        return _resource(
            "binary",
            str(resolved),
            name,
            size=after.st_size,
            modified_at_ns=after.st_mtime_ns,
            format=resource_format,
            message="二进制资源不在文件视图中内联展示",
        )
    return _decode_resource(data, resolved, name, resource_format, after)


def _read_resource_bytes(
    resolved: Path,
    name: str,
    resource_format: OpenableResourceFormat,
    before: os.stat_result,
) -> tuple[bytes, os.stat_result] | OpenableResource:
    try:
        with resolved.open("rb") as handle:
            data = handle.read(OPENABLE_RESOURCE_MAX_BYTES + 1)
        after = resolved.stat()
    except FileNotFoundError:
        return _resource(
            "missing",
            str(resolved),
            name,
            size=None,
            modified_at_ns=None,
            format=resource_format,
            message="资源在读取前被删除",
        )
    except (OSError, ValueError):
        return _resource(
            "unreadable",
            str(resolved),
            name,
            size=before.st_size,
            modified_at_ns=before.st_mtime_ns,
            format=resource_format,
            message="资源读取失败",
        )
    return data, after


def _verify_after_read(
    resolved: Path,
    workspace_root: Path,
    result_root: Path,
    name: str,
    resource_format: OpenableResourceFormat,
    after: os.stat_result,
) -> Path | OpenableResource:
    try:
        after_resolved = resolved.resolve(strict=True)
    except (FileNotFoundError, OSError, ValueError):
        return _resource(
            "missing",
            str(resolved),
            name,
            size=None,
            modified_at_ns=None,
            format=resource_format,
            message="资源在读取后被删除",
        )
    if not _is_within(after_resolved, workspace_root) and not _is_within(
        after_resolved, result_root
    ):
        return _resource(
            "outside_workspace",
            str(resolved),
            name,
            size=after.st_size,
            modified_at_ns=after.st_mtime_ns,
            format=resource_format,
            message="资源读取后指向不允许的路径",
        )
    return after_resolved


def _decode_resource(
    data: bytes,
    resolved: Path,
    name: str,
    resource_format: OpenableResourceFormat,
    after: os.stat_result,
) -> OpenableResource:
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return _resource(
            "encoding_error",
            str(resolved),
            name,
            size=after.st_size,
            modified_at_ns=after.st_mtime_ns,
            format=resource_format,
            message="资源不是有效的 UTF-8 文本",
        )
    return _resource(
        "ready",
        str(resolved),
        name,
        size=after.st_size,
        modified_at_ns=after.st_mtime_ns,
        format=resource_format,
        content=content,
    )


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _changed(
    size: int,
    modified_at_ns: int,
    expected_size: int | None,
    expected_mtime_ns: int | None,
) -> bool:
    return (expected_size is not None and size != expected_size) or (
        expected_mtime_ns is not None and modified_at_ns != expected_mtime_ns
    )


def _resource_name(raw_path: str) -> str:
    return Path(raw_path).name or "资源"


def _format_for_path(path: Path) -> OpenableResourceFormat:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".diff", ".patch"}:
        return "diff"
    return "text"


def _resource(
    status: OpenableResourceStatus,
    path: str,
    name: str,
    *,
    size: int | None,
    modified_at_ns: int | None,
    format: OpenableResourceFormat = "text",
    content: str | None = None,
    message: str | None = None,
) -> OpenableResource:
    return OpenableResource(
        status=status,
        path=path,
        name=name,
        format=format,
        size=size,
        modified_at_ns=modified_at_ns,
        content=content if status == "ready" else None,
        message=message,
    )


__all__ = [
    "OPENABLE_FILE_TOOLS",
    "OPENABLE_RESOURCE_MAX_BYTES",
    "OPENABLE_RESULT_ROOT",
    "OpenableResource",
    "OpenableResourceFormat",
    "OpenableResourceRef",
    "OpenableResourceStatus",
    "openable_resource_for_tool",
    "read_openable_resource",
]
