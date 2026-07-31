from __future__ import annotations

import json
from pathlib import Path

import pytest

from lion_code import session_memory as session_memory_module
from lion_code.core.messages import AssistantMessage, ToolCall, ToolResultMessage
from lion_code.project_identity import ProjectIdentity
from lion_code.session_memory import (
    SessionMemory,
    SessionMemoryError,
    SessionMemoryRepository,
    apply_semantic_patch,
    apply_tool_evidence,
    extract_tool_evidence,
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


def test_tool_evidence_updates_files_verification_and_blockers_only_from_events(
    tmp_path,
) -> None:
    identity = _identity(tmp_path / "repo", "project")
    calls = AssistantMessage(
        model="test",
        stop_reason="toolUse",
        content=[
            ToolCall(
                id="write",
                name="write_file",
                arguments={"file_path": "lion_code/session_memory.py"},
            ),
            ToolCall(
                id="read",
                name="read_file",
                arguments={"file_path": "tests/test_session_memory.py"},
            ),
            ToolCall(
                id="test",
                name="run_shell",
                arguments={"command": "python -m pytest -q"},
            ),
            ToolCall(
                id="lint",
                name="run_shell",
                arguments={"command": "python -m ruff check lion_code"},
            ),
            ToolCall(
                id="failed-edit",
                name="edit_file",
                arguments={"file_path": "broken.py"},
            ),
        ],
    )
    results = [
        ToolResultMessage(tool_call_id="write", tool_name="write_file", content="ok"),
        ToolResultMessage(tool_call_id="read", tool_name="read_file", content="ok"),
        ToolResultMessage(
            tool_call_id="test",
            tool_name="run_shell",
            content="Command failed (exit code 1)",
        ),
        ToolResultMessage(
            tool_call_id="lint",
            tool_name="run_shell",
            content="All checks passed!",
        ),
        ToolResultMessage(
            tool_call_id="failed-edit",
            tool_name="edit_file",
            content="Error editing file: no match",
            is_error=True,
        ),
    ]

    evidence = extract_tool_evidence([calls, *results])
    updated = apply_tool_evidence(SessionMemory.empty(identity.root), evidence)
    semantic = apply_semantic_patch(
        updated,
        {
            "currentGoal": "完成短期记忆",
            "activeTask": "固定快照",
            "pending": ["运行回归"],
            "relevantFiles": ["model-invented.py"],
            "verification": ["model-invented verification"],
        },
    )

    assert semantic.relevant_files == (
        "lion_code/session_memory.py",
        "tests/test_session_memory.py",
    )
    assert semantic.verification == (
        "python -m pytest -q: failed",
        "python -m ruff check lion_code: passed",
    )
    assert any(item.startswith("run_shell failed:") for item in semantic.blockers)
    assert any(item.startswith("edit_file failed:") for item in semantic.blockers)
    assert semantic.current_goal == "完成短期记忆"
    assert semantic.active_task == "固定快照"
    assert semantic.pending == ("运行回归",)
