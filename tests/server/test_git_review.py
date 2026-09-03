"""Git 审查只读快照的应用层与 REST 端点测试。"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from lion_code.application import git_review
from lion_code.application.git_review import (
    MAX_FILES,
    GitReviewError,
    read_git_file_diff,
    read_git_review,
)
from lion_code.application.session import LionCodingSession
from lion_code.server.app import create_app
from tests.application.fakes import FakeCodingSessionBackend

_CAPABILITY = "A" * 43
_APP_ORIGIN = "http://127.0.0.1:8000"


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
    _git(root, "config", "user.email", "review-tests@example.com")
    _git(root, "config", "user.name", "Review Tests")


def _client(cwd: Path) -> TestClient:
    backend = FakeCodingSessionBackend(
        cwd=cwd,
        model="gpt-4o",
        provider_name="openai",
        provider_config_data={
            "use_openai": True,
            "model": "gpt-4o",
            "api_key": "sk-test",
            "base_url": "https://api.test/v1",
        },
    )
    session = LionCodingSession(backend=backend, terminal_output=False)
    return TestClient(
        create_app(session, capability=_CAPABILITY),
        base_url=_APP_ORIGIN,
        headers={"Authorization": f"Bearer {_CAPABILITY}", "Origin": _APP_ORIGIN},
    )


def _make_dirty_repo(root: Path) -> None:
    _git_repository(root)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "keep.txt").write_text("keep\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    (root / "a.py").write_text("x = 1\nx = 2\n", encoding="utf-8")
    (root / "new.py").write_text("y = 9\n", encoding="utf-8")
    _git(root, "add", "new.py")
    _git(root, "rm", "-q", "keep.txt")
    (root / "untracked.md").write_text("z\n", encoding="utf-8")


# ─── 应用层：状态与归类 ───────────────────────────────────────


def test_clean_repo_returns_clean_snapshot() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")

        snapshot = read_git_review(root)

        assert snapshot.state == "ok"
        assert snapshot.clean is True
        assert snapshot.files == ()


def test_dirty_repo_classifies_and_counts_all_statuses() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)

        snapshot = read_git_review(root)

        assert snapshot.state == "ok"
        assert snapshot.clean is False
        by_path = {file.path: file for file in snapshot.files}
        assert by_path["a.py"].status == "modified"
        assert by_path["a.py"].additions == 1
        assert by_path["a.py"].deletions == 0
        assert by_path["new.py"].status == "added"
        assert by_path["new.py"].additions == 1
        assert by_path["keep.txt"].status == "deleted"
        assert by_path["keep.txt"].deletions == 1
        assert by_path["untracked.md"].status == "untracked"
        assert by_path["untracked.md"].additions is None
        # untracked 不计入总增删
        assert snapshot.additions_total == 2
        assert snapshot.deletions_total == 1
        assert snapshot.revision


def test_binary_file_reported_as_binary_without_stats() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
        (root / "bin.dat").write_bytes(b"\x00\x01\x02" * 100)
        _git(root, "add", "bin.dat")

        snapshot = read_git_review(root)

        binary = next(f for f in snapshot.files if f.path == "bin.dat")
        assert binary.binary is True
        assert binary.additions is None
        assert binary.deletions is None


def test_non_git_directory_returns_non_git() -> None:
    with tempfile.TemporaryDirectory() as directory:
        assert read_git_review(Path(directory)).state == "non_git"


def test_unborn_repository_returns_unborn() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")

        snapshot = read_git_review(root)

        assert snapshot.state == "unborn"
        assert snapshot.files == ()


def test_git_failure_is_not_clean() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
        (root / "a.py").write_text("x = 2\n", encoding="utf-8")

        with mock.patch.object(
            git_review, "_run_git", side_effect=OSError("git missing")
        ):
            snapshot = read_git_review(root)

        assert snapshot.state == "git_failed"
        assert snapshot.files == ()


def test_nonzero_status_return_is_git_failed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)

        with mock.patch.object(
            git_review,
            "_run_git",
            side_effect=[(0, "true\n"), (1, "")],
        ):
            snapshot = read_git_review(root)

        assert snapshot.state == "git_failed"
        assert snapshot.clean is False


def test_revision_changes_when_worktree_content_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        tracked = root / "tracked.txt"
        tracked.write_text("before\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")

        tracked.write_text("after one\n", encoding="utf-8")
        first = read_git_review(root)
        tracked.write_text("after two\n", encoding="utf-8")
        second = read_git_review(root)

        assert first.files[0].path == "tracked.txt"
        assert first.revision != second.revision


def test_machine_readable_paths_and_rename_stats() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        old_path = root / "old name.txt"
        old_path.write_text("before\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")

        new_name = "中文 'new name.txt"
        _git(root, "mv", "old name.txt", new_name)
        (root / new_name).write_text("before\nafter\n", encoding="utf-8")

        snapshot = read_git_review(root)
        renamed = next(file for file in snapshot.files if file.status == "renamed")

        assert renamed.path == new_name
        assert renamed.additions == 1
        assert renamed.deletions == 0
        result = read_git_file_diff(root, new_name)
        assert result is not None
        assert result.path == new_name
        assert "+after" in result.diff

        parsed = git_review._parse_status("M  中文 'line\nname.txt\0")
        assert parsed[0].path == "中文 'line\nname.txt"


def test_diff_nonzero_return_is_explicit_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        tracked = root / "tracked.txt"
        tracked.write_text("before\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
        tracked.write_text("after\n", encoding="utf-8")

        original = git_review._run_git

        def fail_diff(cwd: Path, *args: str) -> tuple[int, str]:
            if args and args[0] == "diff":
                return 1, ""
            return original(cwd, *args)

        with mock.patch.object(git_review, "_run_git", side_effect=fail_diff):
            with pytest.raises(GitReviewError):
                read_git_file_diff(root, "tracked.txt")


def test_ancestor_repository_is_not_discovered() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ancestor = Path(directory)
        _git_repository(ancestor)
        workspace = ancestor / "sub"
        workspace.mkdir()

        snapshot = read_git_review(workspace)

        assert snapshot.state == "non_git"


def test_large_change_set_is_truncated() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
        for index in range(MAX_FILES + 5):
            (root / f"f{index:04d}.txt").write_text("x\n", encoding="utf-8")

        snapshot = read_git_review(root)

        assert snapshot.truncated is True
        assert len(snapshot.files) == MAX_FILES


# ─── 应用层：单文件 diff ──────────────────────────────────────


def test_diff_returns_bounded_unified_diff() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
        (root / "a.py").write_text("x = 1\nx = 2\n", encoding="utf-8")

        result = read_git_file_diff(root, "a.py")

        assert result is not None
        assert result.binary is False
        assert result.untracked is False
        assert "+x = 2" in result.diff


def test_diff_reports_binary_without_text() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "bin.dat").write_bytes(b"\x00\x01\x02" * 100)
        _git(root, "add", "bin.dat")
        _git(root, "commit", "-qm", "base")
        (root / "bin.dat").write_bytes(b"\x03\x04\x05" * 100)

        result = read_git_file_diff(root, "bin.dat")

        assert result is not None
        assert result.binary is True
        assert result.diff == ""


def test_diff_untracked_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)

        result = read_git_file_diff(root, "untracked.md")

        assert result is not None
        assert result.untracked is True
        assert result.diff == ""


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../secret.txt",
        "sub/../../secret.txt",
    ],
)
def test_diff_rejects_out_of_workspace_paths(path: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)
        assert read_git_file_diff(root, path) is None


def test_diff_rejects_path_not_in_changeset() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)
        assert read_git_file_diff(root, "unrelated.txt") is None


def test_diff_truncates_large_output() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _git_repository(root)
        (root / "big.py").write_text("a\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "base")
        (root / "big.py").write_text("b\n" * 200_000, encoding="utf-8")

        result = read_git_file_diff(root, "big.py")

        assert result is not None
        assert result.truncated is True
        assert len(result.diff.encode("utf-8")) <= git_review.MAX_DIFF_BYTES


# ─── REST 端点 ────────────────────────────────────────────────


def test_git_review_endpoint_requires_capability() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)
        client = TestClient(
            create_app(_session(root), capability=_CAPABILITY),
            base_url=_APP_ORIGIN,
        )

        response = client.get("/api/git/review")

        assert response.status_code == 401


def test_git_review_endpoint_returns_snapshot() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)
        client = _client(root)

        response = client.get("/api/git/review")

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "ok"
        assert data["clean"] is False
        paths = {item["path"] for item in data["files"]}
        assert "a.py" in paths
        assert "untracked.md" in paths
        assert data["additions_total"] == 2
        assert data["deletions_total"] == 1


def test_git_review_diff_endpoint_and_invalid_path() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)
        client = _client(root)

        ok = client.get("/api/git/review/diff", params={"path": "a.py"})
        assert ok.status_code == 200
        assert "+x = 2" in ok.json()["diff"]

        invalid = client.get("/api/git/review/diff", params={"path": "../secret"})
        assert invalid.status_code == 422


def test_git_review_diff_endpoint_reports_git_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _make_dirty_repo(root)
        client = _client(root)

        with mock.patch(
            "lion_code.server.app.read_git_file_diff",
            side_effect=GitReviewError("git failed"),
        ):
            response = client.get("/api/git/review/diff", params={"path": "a.py"})

        assert response.status_code == 503
        assert response.json()["detail"] == "Git 读取失败"


def _session(root: Path) -> LionCodingSession:
    backend = FakeCodingSessionBackend(
        cwd=root,
        model="gpt-4o",
        provider_name="openai",
        provider_config_data={
            "use_openai": True,
            "model": "gpt-4o",
            "api_key": "sk-test",
            "base_url": "https://api.test/v1",
        },
    )
    return LionCodingSession(backend=backend, terminal_output=False)
