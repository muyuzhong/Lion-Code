"""Executable dependency guards for the application port boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _source_files(*parts: str) -> tuple[Path, ...]:
    root = SOURCE_ROOT.joinpath(*parts)
    return tuple(
        path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts
    )


def _source_key(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


def _application_files() -> tuple[Path, ...]:
    return _source_files("application")


def _attribute_names(path: Path) -> set[str]:
    return {
        node.attr for node in ast.walk(_tree(path)) if isinstance(node, ast.Attribute)
    }


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    package = path.relative_to(SOURCE_ROOT).parts[:-1]
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "lion_code" and len(parts) > 1:
                    roots.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = list(package[: len(package) - node.level + 1])
                if node.module:
                    target.extend(node.module.split("."))
                if target:
                    roots.add(target[0])
            elif node.module and node.module.startswith("lion_code."):
                roots.add(node.module.split(".")[1])
    return roots


def _forbidden_root_imports(
    paths: tuple[Path, ...], forbidden: set[str]
) -> dict[str, tuple[str, ...]]:
    violations: dict[str, tuple[str, ...]] = {}
    for path in paths:
        found = tuple(sorted(_imported_roots(path) & forbidden))
        if found:
            violations[_source_key(path)] = found
    return violations


def test_application_only_imports_consumer_side_dependencies() -> None:
    violations = _forbidden_root_imports(_application_files(), {"agent", "runtime"})
    assert not violations, violations


def test_application_does_not_import_runtime_or_harness_symbols() -> None:
    forbidden_names = {"Agent", "AgentHarness", "LionAgentRuntime"}
    violations: dict[str, list[str]] = {}
    for path in _application_files():
        found: set[str] = set()
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name in forbidden_names:
                        found.add(alias.name)
        if found:
            violations[_source_key(path)] = sorted(found)
    assert not violations, violations


def test_application_does_not_reference_harness_storage_or_queue_types() -> None:
    violations = {
        _source_key(path): sorted(
            _attribute_names(path) & {"harness", "queued_messages", "core_runtime"}
        )
        for path in _application_files()
        if _attribute_names(path) & {"harness", "queued_messages", "core_runtime"}
    }
    assert not violations, violations


def test_runtime_implementation_does_not_import_application() -> None:
    runtime_files = _source_files("runtime")
    violations = _forbidden_root_imports(runtime_files, {"application"})
    assert not violations, violations


def test_tui_does_not_import_runtime_engine() -> None:
    violations = _forbidden_root_imports(_source_files("tui"), {"agent", "runtime"})
    assert not violations, violations


def test_fake_backend_is_a_real_application_injection() -> None:
    fake_path = REPOSITORY_ROOT / "tests" / "application" / "fakes.py"
    fake_source = fake_path.read_text(encoding="utf-8")
    fake_tree = _tree(fake_path)
    imported_modules = {
        node.module
        for node in ast.walk(fake_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        module == "lion_code.adapters" or module.startswith("lion_code.adapters.")
        for module in imported_modules
    )
    assert "LionCodingSession" not in fake_source
