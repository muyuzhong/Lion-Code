from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lion_code import project_identity


def test_git_root_gives_subdirectories_one_project_identity(monkeypatch, tmp_path) -> None:
    root = tmp_path / "repo"
    child = root / "packages" / "api"
    other_root = tmp_path / "other-repo"
    child.mkdir(parents=True)
    other_root.mkdir()

    def git_root(args, **_kwargs):
        cwd = Path(args[2]).resolve()
        root_for_cwd = root if cwd.is_relative_to(root) else other_root
        return SimpleNamespace(returncode=0, stdout=f"{root_for_cwd}\n")

    monkeypatch.setattr(
        project_identity.subprocess,
        "run",
        git_root,
    )

    from_root = project_identity.resolve_project_identity(root)
    from_child = project_identity.resolve_project_identity(child)
    from_other_root = project_identity.resolve_project_identity(other_root)

    assert from_root.root == from_child.root == root.resolve()
    assert from_root.key == from_child.key
    assert from_other_root.key != from_root.key
    assert from_child.is_git


def test_non_git_identity_uses_normalized_cwd(monkeypatch, tmp_path) -> None:
    cwd = tmp_path / "scratch" / "work"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(
        project_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )

    direct = project_identity.resolve_project_identity(cwd)
    normalized = project_identity.resolve_project_identity(cwd / ".." / "work")

    assert direct.root == normalized.root == cwd.resolve()
    assert direct.key == normalized.key
    assert not direct.is_git
