"""Tool capability routing guards for the Agent decoupling boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
REMOVED_ROUTE_NAMES = (
    "AgentToolController",
    "context.controller",
    "run_skill_tool",
    "run_subagent_tool",
    "enter_plan_mode_tool",
    "exit_plan_mode_tool",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _production_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _class_fields(tree: ast.Module, class_name: str) -> set[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return {
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
    return set()


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(_source(path), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def test_tool_context_has_no_controller_field() -> None:
    fields = _class_fields(
        ast.parse(_source(SOURCE_ROOT / "tooling" / "context.py")),
        "ToolContext",
    )
    assert "controller" not in fields


def test_removed_agent_tool_route_names_have_no_production_residue() -> None:
    violations = {
        path.relative_to(SOURCE_ROOT).as_posix(): [
            name for name in REMOVED_ROUTE_NAMES if name in _source(path)
        ]
        for path in _production_files()
        if any(name in _source(path) for name in REMOVED_ROUTE_NAMES)
    }
    assert violations == {}


def test_capability_and_executor_modules_do_not_import_agent() -> None:
    checked = (
        SOURCE_ROOT / "capabilities",
        SOURCE_ROOT / "skill_runtime.py",
        SOURCE_ROOT / "subagent_runtime.py",
    )
    violations: dict[str, list[str]] = {}
    paths = [
        path
        for root in checked
        for path in (root.rglob("*.py") if root.is_dir() else (root,))
    ]
    for path in paths:
        imported = _imported_modules(path)
        bad = sorted(
            module
            for module in imported
            if module == "lion_code.agent"
            or module.endswith(".agent")
            or module == "lion_code.core.harness"
        )
        if bad:
            violations[path.relative_to(SOURCE_ROOT).as_posix()] = bad
    assert violations == {}


def test_capability_factories_require_bound_dependencies() -> None:
    skill_source = _source(SOURCE_ROOT / "capabilities" / "skill.py")
    subagent_source = _source(SOURCE_ROOT / "capabilities" / "subagent.py")
    assert "def create_skill_capability(runtime: SkillRuntime)" in skill_source
    assert "def create_subagent_capability(executor: SubagentExecutor)" in (
        subagent_source
    )
