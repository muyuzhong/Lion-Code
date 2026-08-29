from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lion_code.tooling.snapshot import WorkspaceSnapshot

def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

def _git_repository(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "snapshot-tests@example.com")
    _git(root, "config", "user.name", "Snapshot Tests")

class TestWorkspaceSnapshot(unittest.TestCase):

    def test_ignored_and_sensitive_files_store_metadata_only(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as storage_directory,
        ):
            root = Path(directory)
            storage = Path(storage_directory)
            _git_repository(root)
            (root / ".gitignore").write_text(
                "ignored.txt\n.env*\n.credentials/\n.secrets/\n",
                encoding="utf-8",
            )
            _git(root, "add", ".gitignore")
            _git(root, "commit", "-qm", "ignore rules")
            (root / "ignored.txt").write_text("ignored body", encoding="utf-8")
            (root / ".env.local").write_text("TOKEN=do-not-copy", encoding="utf-8")
            credentials = root / ".credentials"
            credentials.mkdir()
            (credentials / "token").write_text("credential-body", encoding="utf-8")
            secrets = root / ".secrets"
            secrets.mkdir()
            (secrets / "key").write_text("secret-body", encoding="utf-8")

            snapshot_id = WorkspaceSnapshot(root, storage).create()
            manifest_path = storage / snapshot_id / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = {entry["path"]: entry for entry in manifest["entries"]}

            for path in (
                "ignored.txt",
                ".env.local",
                ".credentials/token",
                ".secrets/key",
            ):
                self.assertIn(path, entries)
                self.assertNotIn("content", entries[path])
                self.assertIn("size", entries[path])
                self.assertIn("mtime", entries[path])
                self.assertIn("mtime_ns", entries[path])

            stored_bytes = b"".join(
                path.read_bytes() for path in storage.rglob("*") if path.is_file()
            )
            self.assertNotIn(b"do-not-copy", stored_bytes)
            self.assertNotIn(b"credential-body", stored_bytes)
            self.assertNotIn(b"secret-body", stored_bytes)

    def test_gc_keeps_newest_configured_number(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as storage_directory,
        ):
            root = Path(directory)
            storage = Path(storage_directory)
            snapshot = WorkspaceSnapshot(
                root,
                storage,
                max_snapshots=2,
                retention_window_seconds=None,
            )
            first = snapshot.create()
            (root / "state.txt").write_text("second", encoding="utf-8")
            second = snapshot.create()
            (root / "state.txt").write_text("third", encoding="utf-8")
            third = snapshot.create()

            self.assertFalse((storage / first).exists())
            self.assertTrue((storage / second).exists())
            self.assertTrue((storage / third).exists())
            self.assertLessEqual(
                len([path for path in storage.iterdir() if path.is_dir()]), 2
            )

    def test_gc_removes_snapshots_outside_retention_window(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as storage_directory,
        ):
            root = Path(directory)
            storage = Path(storage_directory)
            snapshot = WorkspaceSnapshot(
                root,
                storage,
                max_snapshots=20,
                retention_window_seconds=0,
            )
            first = snapshot.create()
            (root / "state.txt").write_text("new", encoding="utf-8")
            second = snapshot.create()

            self.assertFalse((storage / first).exists())
            self.assertTrue((storage / second).exists())

if __name__ == "__main__":
    unittest.main()
