"""工作区文件系统快照与恢复。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat as stat_module
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

SnapshotId = str
_DEFAULT_RETENTION_WINDOW_SECONDS = 30 * 24 * 60 * 60

def is_sensitive_path(path: str | Path) -> bool:
    """判断路径是否属于不应保存内容的敏感路径。"""
    parts = PurePosixPath(str(path).replace("\\", "/")).parts
    return any(
        part in {".credentials", ".secrets"} or part.startswith(".env")
        for part in parts
    )

class WorkspaceSnapshot:
    """在工作区外保存文件树，并提供可逆的文件系统恢复。"""

    def __init__(
        self,
        workspace_root: str | Path,
        storage_dir: str | Path | None = None,
        *,
        max_snapshots: int = 20,
        retention_window_seconds: float | None = _DEFAULT_RETENTION_WINDOW_SECONDS,
    ) -> None:
        if max_snapshots < 1:
            raise ValueError("max_snapshots must be positive")
        if retention_window_seconds is not None and retention_window_seconds < 0:
            raise ValueError("retention_window_seconds must not be negative")
        self.workspace_root = Path(workspace_root).resolve()
        self.storage_dir = Path(
            storage_dir or _default_storage_dir(self.workspace_root)
        ).resolve()
        if self._is_within(self.storage_dir, self.workspace_root):
            raise ValueError("snapshot storage must be outside the workspace")
        self.max_snapshots = max_snapshots
        self.retention_window_seconds = retention_window_seconds
        self._lock = threading.RLock()
        self._last_created_ns = 0

    def create(self) -> SnapshotId:
        """捕获当前工作区状态，不修改 Git index 或工作区。"""
        return self._create(protected=())

    def _create(self, *, protected: tuple[SnapshotId, ...]) -> SnapshotId:
        with self._lock:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            entries = self._capture_entries()
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            _chmod_private(self.storage_dir)
            snapshot_id = uuid.uuid4().hex
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{snapshot_id}-", dir=self.storage_dir)
            )
            try:
                data_dir = temporary / "data"
                data_dir.mkdir()
                manifest_entries: list[dict[str, Any]] = []
                for entry in entries:
                    manifest_entry = dict(entry)
                    path = self._safe_relative(entry["path"])
                    source = self.workspace_root / Path(path)
                    if (
                        entry["exists"]
                        and not entry["sensitive"]
                        and not entry["ignored"]
                    ):
                        self._copy_entry(source, data_dir / Path(path), entry["kind"])
                        manifest_entry["content"] = str(Path(path).as_posix())
                    manifest_entries.append(manifest_entry)
                created_ns = max(time.time_ns(), self._last_created_ns + 1)
                self._last_created_ns = created_ns
                manifest = {
                    "version": 1,
                    "snapshot_id": snapshot_id,
                    "created_ns": created_ns,
                    "entries": manifest_entries,
                }
                _write_private_json(temporary / "manifest.json", manifest)
                final_dir = self.storage_dir / snapshot_id
                temporary.replace(final_dir)
                _chmod_private_tree(final_dir)
                self._gc(protected={snapshot_id, *protected})
                return snapshot_id
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

    def _capture_entries(self) -> list[dict[str, Any]]:
        git_paths = self._git_paths()
        if git_paths is None:
            candidates = self._filesystem_paths()
            ignored: set[str] = set()
        else:
            tracked, untracked, ignored = git_paths
            candidates = tracked | untracked | ignored

        entries: list[dict[str, Any]] = []
        for relative in sorted(candidates):
            safe = self._safe_relative(relative)
            path = self.workspace_root / safe
            sensitive = is_sensitive_path(relative)
            is_ignored = relative in ignored
            try:
                file_stat = path.lstat()
            except FileNotFoundError:
                file_stat = None
            kind = "missing"
            exists = file_stat is not None
            if file_stat is not None:
                if stat_module.S_ISLNK(file_stat.st_mode):
                    kind = "symlink"
                elif stat_module.S_ISREG(file_stat.st_mode):
                    kind = "file"
                else:
                    continue
            entries.append(
                {
                    "path": relative,
                    "exists": exists,
                    "kind": kind,
                    "mode": file_stat.st_mode & 0o777 if file_stat else 0,
                    "size": file_stat.st_size if file_stat else 0,
                    "mtime": file_stat.st_mtime if file_stat else 0,
                    "mtime_ns": file_stat.st_mtime_ns if file_stat else 0,
                    "sensitive": sensitive,
                    "ignored": is_ignored,
                }
            )
        return entries

    def _git_paths(self) -> tuple[set[str], set[str], set[str]] | None:
        try:
            git_root = Path(
                os.fsdecode(self._git("rev-parse", "--show-toplevel")).strip()
            ).resolve()
        except (OSError, subprocess.CalledProcessError):
            return None

        try:
            prefix = self.workspace_root.relative_to(git_root).as_posix()
        except ValueError:
            return None
        pathspec = [prefix] if prefix and prefix != "." else []

        try:
            head = self._git(
                "ls-tree",
                "-r",
                "-z",
                "--name-only",
                "HEAD",
                "--",
                *pathspec,
            )
        except subprocess.CalledProcessError:
            # An initialized repository without a commit has no HEAD tree,
            # but its index and ignore rules are still valid snapshot inputs.
            head = b""
        try:
            cached = self._git("ls-files", "-z", "--cached", "--", *pathspec)
            untracked = self._git(
                "ls-files", "-z", "--others", "--exclude-standard", "--", *pathspec
            )
            ignored = self._git(
                "ls-files",
                "-z",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                *pathspec,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return (
            self._scope_git_paths(
                _split_git_paths(head) | _split_git_paths(cached), prefix
            ),
            self._scope_git_paths(_split_git_paths(untracked), prefix),
            self._scope_git_paths(_split_git_paths(ignored), prefix),
        )

    @staticmethod
    def _scope_git_paths(paths: set[str], prefix: str) -> set[str]:
        if not prefix or prefix == ".":
            return paths
        scoped: set[str] = set()
        prefix_with_separator = f"{prefix}/"
        for path in paths:
            if path.startswith(prefix_with_separator):
                scoped.add(path[len(prefix_with_separator) :])
        return scoped

    def _git(self, *args: str, timeout: float = 5.0) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.workspace_root), *args],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        return result.stdout

    def _is_ignored_path(self, relative: str) -> bool:
        try:
            self._git("check-ignore", "-q", "--", relative)
        except (OSError, subprocess.CalledProcessError):
            return False
        return True

    def _filesystem_paths(self) -> set[str]:
        paths: set[str] = set()
        for root, directories, files in os.walk(self.workspace_root, followlinks=False):
            directories[:] = [
                directory for directory in directories if directory != ".git"
            ]
            files[:] = [file for file in files if file != ".git"]
            for name in files:
                path = Path(root) / name
                paths.add(path.relative_to(self.workspace_root).as_posix())
            for name in directories:
                path = Path(root) / name
                if os.path.islink(path):
                    paths.add(path.relative_to(self.workspace_root).as_posix())
        return paths

    def _copy_entry(self, source: Path, destination: Path, kind: str) -> None:
        if kind == "symlink":
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.readlink(source))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination, follow_symlinks=False)

    def _safe_relative(self, relative: str) -> str:
        normalized = relative.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or PureWindowsPath(normalized).is_absolute()
            or not normalized
            or normalized == "."
            or ".." in path.parts
            or ".git" in path.parts
        ):
            raise ValueError(f"unsafe workspace path: {relative}")
        return path.as_posix()

    def _gc(self, *, protected: set[str]) -> None:
        snapshots: list[tuple[int, Path]] = []
        for directory in self.storage_dir.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            manifest_path = directory / "manifest.json"
            try:
                with manifest_path.open(encoding="utf-8") as stream:
                    created_ns = int(json.load(stream).get("created_ns", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            snapshots.append((created_ns, directory))
        snapshots.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        keep = {path.name for _, path in snapshots[: self.max_snapshots]}
        if self.retention_window_seconds is not None:
            cutoff_ns = time.time_ns() - int(
                self.retention_window_seconds * 1_000_000_000
            )
            keep = {
                path.name
                for created_ns, path in snapshots
                if path.name in keep and created_ns >= cutoff_ns
            }
        keep.update(protected)
        for _, directory in snapshots:
            if directory.name not in keep:
                shutil.rmtree(directory)

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
        except ValueError:
            return False
        return True

def _split_git_paths(output: bytes) -> set[str]:
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in output.split(b"\0")
        if item
    }

def _default_storage_dir(workspace_root: Path) -> Path:
    workspace_key = hashlib.sha256(os.fsencode(str(workspace_root))).hexdigest()[:16]
    return Path.home() / ".lion_code" / "snapshots" / workspace_key

def _chmod_private(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        pass

def _write_private_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass

def _chmod_private_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass
