from __future__ import annotations

import json
from pathlib import Path

import pytest

from lion_code import session_memory as session_memory_module
from lion_code.project_identity import ProjectIdentity
from lion_code.session_memory import (
    SessionMemory,
    SessionMemoryError,
    SessionMemoryRepository,
)


def _identity(root: Path, key: str) -> ProjectIdentity:
    root.mkdir()
    return ProjectIdentity(root=root.resolve(), key=key, is_git=True)


def test_session_memory_persists_the_project_working_state(tmp_path) -> None:
    identity = _identity(tmp_path / "repo", "project")
    repository = SessionMemoryRepository(identity, storage_dir=tmp_path / "state")
    memory = SessionMemory(
        project_root=str(identity.root),
        current_goal="完成项目记忆",
        active_task="实现存储",
        completed=("项目身份",),
        pending=("固定快照",),
        decisions=("JSONL 保持完整历史",),
        blockers=("等待验证",),
        relevant_files=("lion_code/session_memory.py",),
        verification=("pytest 通过",),
        previous_handoff="继续持久化切片",
        next_step="接入 Agent 生命周期",
    )

    saved = repository.save(memory)
    restored = SessionMemoryRepository(
        identity,
        storage_dir=tmp_path / "state",
    ).load()

    assert restored == saved
    assert restored.updated_at is not None
    payload = json.loads(repository.path.read_text(encoding="utf-8"))
    assert payload["projectRoot"] == str(identity.root)
    assert payload["activeTask"] == "实现存储"


def test_different_project_identities_use_separate_session_memory(monkeypatch, tmp_path) -> None:
    first = _identity(tmp_path / "first", "first")
    second = _identity(tmp_path / "second", "second")
    monkeypatch.setattr(
        session_memory_module,
        "project_storage_dir",
        lambda identity: tmp_path / "stores" / identity.key,
    )
    first_repository = SessionMemoryRepository(first)
    second_repository = SessionMemoryRepository(second)

    first_repository.save(
        SessionMemory(project_root=str(first.root), current_goal="first goal")
    )

    assert first_repository.path != second_repository.path
    assert second_repository.load().current_goal is None


def test_corrupt_session_memory_is_reported_without_overwriting_file(tmp_path) -> None:
    identity = _identity(tmp_path / "repo", "project")
    repository = SessionMemoryRepository(identity, storage_dir=tmp_path / "state")
    repository.path.parent.mkdir()
    repository.path.write_text("{not json", encoding="utf-8")
    original = repository.path.read_bytes()

    with pytest.raises(SessionMemoryError, match="Unable to read Session Memory"):
        repository.load()

    assert repository.path.read_bytes() == original
