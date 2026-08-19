"""Provider 配置与 Thinking 所有权的可执行架构约束。"""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
PROVIDER_FIELDS = {
    "model",
    "provider_kind",
    "api_key",
    "openai_base_url",
    "anthropic_base_url",
    "thinking_enabled",
    "thinking_level",
}
REMOVED_AGENT_MIRRORS = {
    "model",
    "use_openai",
    "thinking",
    "_api_key",
    "_api_base",
    "_anthropic_base_url",
    "_thinking_mode",
    "_thinking_level",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _class_fields(node: ast.ClassDef) -> set[str]:
    return {
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    }


def _self_assignments(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for statement in ast.walk(node):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                names.add(target.attr)
    return names


def _attribute_assignments(
    tree: ast.Module,
    attributes: set[str],
    *,
    bases: set[str] | None = None,
) -> list[ast.Assign]:
    matches: list[ast.Assign] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = node.targets
        if any(
            isinstance(target, ast.Attribute)
            and target.attr in attributes
            and (
                bases is None
                or (isinstance(target.value, ast.Name) and target.value.id in bases)
            )
            for target in targets
        ):
            matches.append(node)
    return matches


def test_provider_state_and_view_have_explicit_boundaries() -> None:
    tree = _tree(SOURCE_ROOT / "runtime" / "provider.py")
    state = _class(tree, "ProviderState")
    view = _class(tree, "ProviderView")

    assert _class_fields(state) == PROVIDER_FIELDS
    assert _class_fields(view) == {
        "model",
        "provider_kind",
        "thinking_enabled",
        "thinking_level",
    }
    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "dataclass"
        and any(
            keyword.arg == "frozen"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
        for decorator in view.decorator_list
    )


def test_provider_manager_has_no_agent_dependency_or_constructor_argument() -> None:
    tree = _tree(SOURCE_ROOT / "runtime" / "provider.py")
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert all("agent" not in name.casefold() for name in imported_names)

    manager = _class(tree, "ProviderManager")
    init = next(
        node
        for node in manager.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assert all(argument.arg.casefold() != "agent" for argument in init.args.args)
    assert all(
        "agent" not in ast.unparse(argument.annotation).casefold()
        for argument in init.args.args
        if argument.annotation is not None
    )


def test_provider_state_field_writes_are_confined_to_provider_manager() -> None:
    violations: list[str] = []
    for path in (
        SOURCE_ROOT / "agent.py",
        SOURCE_ROOT / "runtime" / "session_lifecycle.py",
    ):
        if _attribute_assignments(
            _tree(path),
            PROVIDER_FIELDS,
            bases={"self", "identity"},
        ):
            violations.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert violations == []


def test_agent_has_no_provider_mutable_mirrors() -> None:
    agent_class = _class(_tree(SOURCE_ROOT / "agent.py"), "Agent")
    assert not REMOVED_AGENT_MIRRORS & _self_assignments(agent_class)


def test_session_restore_uses_provider_manager_command() -> None:
    tree = _tree(SOURCE_ROOT / "runtime" / "session_lifecycle.py")
    source = (SOURCE_ROOT / "runtime" / "session_lifecycle.py").read_text(
        encoding="utf-8"
    )

    assert "provider_manager.restore_configuration" in source
    assert not _attribute_assignments(
        tree,
        {
            "model",
            "_thinking_level",
            "_thinking_mode",
            "_api_key",
            "_api_base",
            "_anthropic_base_url",
        },
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_apply_core_thinking_level"
        for node in ast.walk(tree)
    )
