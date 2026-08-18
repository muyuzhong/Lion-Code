"""Supervisor Plane 的依赖、状态形状和 Profile 隔离门禁。"""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from lion_code.supervisor import SupervisorState

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
SUPERVISOR_PATH = SOURCE_ROOT / "supervisor.py"

_FORBIDDEN_IMPORTS = {
    "lion_code.agent",
    "lion_code.agent_runtime",
    "lion_code.application",
    "lion_code.capabilities",
    "lion_code.composition",
    "lion_code.context",
    "lion_code.core.harness",
    "lion_code.permission_state",
    "lion_code.provider_manager",
    "lion_code.providers",
    "lion_code.session_identity",
    "lion_code.session_lifecycle",
    "lion_code.session_runtime",
    "lion_code.tooling",
    "lion_code.tui",
    "lion_code.usage",
}
_FORBIDDEN_TERMS = {
    "MemoryRepository",
    "SessionMemory",
    "Dream",
    "Learning",
    "relevant-memory",
    "semantic memory",
    "embedding",
    "final_text",
    "messages",
    "transcript",
}
_CONTROL_FIELDS = {
    "goal_id",
    "goal",
    "phase",
    "status",
    "attempt",
    "session_id",
    "retry_count",
    "last_stop_reason",
    "last_error",
    "created_at",
    "updated_at",
    "next_run_at",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_supervisor_imports_only_public_core_events_and_stdlib() -> None:
    tree = ast.parse(_source(SUPERVISOR_PATH), filename=str(SUPERVISOR_PATH))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.add(f"lion_code.{module}" if node.level else module)

    assert not imports & _FORBIDDEN_IMPORTS
    assert "lion_code.core.events" in imports
    assert all(
        not module.startswith("lion_code.") or module == "lion_code.core.events"
        for module in imports
    )


def test_supervisor_source_has_no_agent_content_or_removed_state_terms() -> None:
    source = _source(SUPERVISOR_PATH)
    assert not {
        term for term in _FORBIDDEN_TERMS if term.casefold() in source.casefold()
    }


def test_checkpoint_state_is_only_execution_control() -> None:
    assert {field.name for field in fields(SupervisorState)} == _CONTROL_FIELDS


def test_profiles_agent_and_composition_do_not_know_supervisor() -> None:
    paths = (
        SOURCE_ROOT / "agent.py",
        SOURCE_ROOT / "meta_agent.py",
        SOURCE_ROOT / "composition" / "profiles.py",
        SOURCE_ROOT / "composition" / "agent_builder.py",
    )
    violations = {
        str(path.relative_to(SOURCE_ROOT)): line
        for path in paths
        for line in _source(path).splitlines()
        if "supervisor" in line.casefold()
    }
    assert violations == {}


def test_supervisor_event_projection_reads_only_public_event_type() -> None:
    tree = ast.parse(_source(SUPERVISOR_PATH), filename=str(SUPERVISOR_PATH))
    event_attribute_reads = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "event"
    }
    assert event_attribute_reads <= {"type"}
