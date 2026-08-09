from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable
from pathlib import Path

from _boundaries import ALL_ROOTS, BOUNDARIES

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

# Import-direction boundaries live in _boundaries.py (single source of truth).
# AST tests and import-linter config both derive from those definitions.
_CORE = BOUNDARIES[0]
_PROVIDERS = BOUNDARIES[1]
_APPLICATION = BOUNDARIES[2]
_TUI = BOUNDARIES[3]
_PRODUCTION = BOUNDARIES[4]

LEGACY_MESSAGE_SYMBOLS = frozenset({"_anthropic_messages", "_openai_messages"})
HARNESS_MUTATION_METHODS = frozenset({"clear_queues", "follow_up", "replace_messages"})
SESSION_RECORDER_SITES = {
    "agent.py": frozenset({"Agent._migrate_legacy_core_session"}),
    "agent_runtime.py": frozenset({"AgentRuntimeCoordinator.reset_core_observers"}),
}
JSONL_WRITER_SYMBOLS = frozenset({"JsonlSessionStorage", "entry_to_json_line"})
MEMORY_INDEX_REBUILD_SYMBOLS = frozenset(
    {"_update_memory_index", "rebuild_memory_index_if_needed"}
)
REMOVED_SKILL_COMMAND_SYMBOLS = frozenset(
    {
        "SkillInvocation",
        "expand_skill_command",
        "format_skill_invocation",
        "parse_skill_invocation",
    }
)
MCP_LIFECYCLE_CLASS_NAMES = frozenset({"McpConnection", "McpManager"})
PROVIDER_SHIM_EXPORTS = ("ModelProvider",)
REMOVED_RUNTIME_SYMBOLS = frozenset(
    {
        "SimpleCancellationToken",
        "ToolCancellationToken",
        "_aborted",
        "_confirmed_paths",
        "cancellation_fn",
        "confirmed_paths",
    }
)
_PERMISSION_STATE_BASE_NAMES = frozenset(
    {"state", "_state", "permission_state", "_permission_state"}
)
_PLAN_STATE_BASE_NAMES = frozenset({"state", "_state", "plan_state", "_plan_state"})
_PLAN_STATE_FIELDS = frozenset(
    {
        "status",
        "file_path",
        "previous_permission_mode",
        "pending_context_reset",
    }
)
_REMOVED_AGENT_PLAN_SYMBOLS = frozenset(
    {
        "_pre_plan_mode",
        "_plan_file_path",
        "_plan_approval_fn",
        "_pending_core_context_reset",
        "_generate_plan_file_path",
        "_build_plan_mode_prompt",
        "_execute_plan_mode_tool",
    }
)
_MUTATING_SET_METHODS = frozenset(
    {
        "add",
        "clear",
        "difference_update",
        "discard",
        "intersection_update",
        "pop",
        "remove",
        "symmetric_difference_update",
        "update",
    }
)

# Dynamic import calls that bypass static import analysis (import-linter / AST).
DYNAMIC_IMPORT_CALLS = frozenset({"import_module", "__import__"})
# Modules allowed to use dynamic imports.  Currently empty — adding a dynamic
# import requires consciously extending this allowlist.
DYNAMIC_IMPORT_ALLOWLIST: frozenset[str] = frozenset()

# Frozen allowlist of self.* fields in provider files.  Any new field requires
# updating this mapping to force conscious review of whether it constitutes
# conversation history storage.
PROVIDER_STATE_ALLOWLIST: dict[str, frozenset[str]] = {
    "providers/anthropic.py": frozenset(
        {
            "_client",
            "_config",
            "_owns_client",
            "arguments_parts",
            "id",
            "name",
        }
    ),
    "providers/fake.py": frozenset({"_streams", "calls"}),
    "providers/openai_compatible.py": frozenset(
        {
            "_client",
            "_config",
            "_content_parts",
            "_finish_reason",
            "_owns_client",
            "_reasoning_items",
            "_status",
            "_thinking_parts",
            "_thinking_signature",
            "_tool_call_builders",
            "_usage",
            "arguments_final",
            "arguments_parts",
            "call_id",
            "emitted_content",
            "fatal",
            "id",
            "name",
            "output_index",
        }
    ),
}


def _source_files(*parts: str) -> tuple[Path, ...]:
    root = SOURCE_ROOT.joinpath(*parts)
    return tuple(
        path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts
    )


def _source_key(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _package_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(SOURCE_ROOT).parts[:-1]


def _module_root(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "lion_code":
        return None
    return parts[1] if len(parts) > 1 else "<package-root>"


def _relative_module_root(path: Path, node: ast.ImportFrom) -> str:
    package = _package_parts(path)
    parents_to_leave = node.level - 1
    if parents_to_leave > len(package):
        return "<outside-package>"

    target = package[: len(package) - parents_to_leave]
    if node.module:
        target += tuple(node.module.split("."))
    return target[0] if target else "<package-root>"


def _product_import_roots(path: Path, tree: ast.Module) -> frozenset[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if root is not None:
                    roots.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                roots.add(_relative_module_root(path, node))
                continue
            if node.module == "lion_code":
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
                continue
            if node.module:
                root = _module_root(node.module)
                if root is not None:
                    roots.add(root)
    return frozenset(roots)


def _unexpected_imports(
    paths: Iterable[Path],
    *,
    allowed: frozenset[str],
) -> dict[str, tuple[str, ...]]:
    violations: dict[str, tuple[str, ...]] = {}
    for path in paths:
        unexpected = tuple(sorted(_product_import_roots(path, _tree(path)) - allowed))
        if unexpected:
            violations[_source_key(path)] = unexpected
    return violations


def _forbidden_imports(
    paths: Iterable[Path],
    *,
    forbidden: frozenset[str],
) -> dict[str, tuple[str, ...]]:
    violations: dict[str, tuple[str, ...]] = {}
    for path in paths:
        found = tuple(sorted(_product_import_roots(path, _tree(path)) & forbidden))
        if found:
            violations[_source_key(path)] = found
    return violations


def _self_fields(tree: ast.Module) -> set[str]:
    fields: set[str] = set()
    for node in ast.walk(tree):
        targets: tuple[ast.expr, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.AugAssign):
            targets = (node.target,)
        for target in targets:
            fields.update(_self_fields_from_target(target))

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (
                node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "self"
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                fields.add(node.args[1].value)
    return fields


def _self_fields_from_target(target: ast.expr) -> set[str]:
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return {target.attr}
    if isinstance(target, (ast.List, ast.Tuple)):
        return {
            field
            for element in target.elts
            for field in _self_fields_from_target(element)
        }
    return set()


_PRIVATE_HISTORY_KEYWORDS = frozenset(
    {
        "messages",
        "history",
        "conversation",
        "transcript",
        "turns",
    }
)


def _private_history_fields(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        field
        for field in _self_fields(tree)
        if any(kw in field.casefold() for kw in _PRIVATE_HISTORY_KEYWORDS)
    )


def _sink_symbols(tree: ast.Module) -> frozenset[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "set_sink":
                symbols.add("set_sink")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "set_sink":
                symbols.add("set_sink")
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "set_sink":
                symbols.add("set_sink")
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "set_sink"
            ):
                symbols.add("set_sink")
    return frozenset(symbols)


def _legacy_symbols(tree: ast.Module) -> frozenset[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            name = node.name
        elif isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            name = node.args[1].value
        if name in LEGACY_MESSAGE_SYMBOLS:
            symbols.add(name)
    return frozenset(symbols)


def _legacy_symbol_locations(
    paths: Iterable[Path],
) -> dict[str, frozenset[str]]:
    locations = {symbol: set() for symbol in LEGACY_MESSAGE_SYMBOLS}
    for path in paths:
        for symbol in _legacy_symbols(_tree(path)):
            locations[symbol].add(_source_key(path))
    return {symbol: frozenset(found) for symbol, found in locations.items()}


def _defined_symbols(tree: ast.Module, names: frozenset[str]) -> frozenset[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            if node.name in names:
                symbols.add(node.name)
    return frozenset(symbols)


def _referenced_symbols(tree: ast.Module, names: frozenset[str]) -> frozenset[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in names:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            found.add(node.attr)
        elif isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            if node.name in names:
                found.add(node.name)
        elif isinstance(node, ast.arg) and node.arg in names:
            found.add(node.arg)
    return frozenset(found)


def _class_annotated_fields(tree: ast.Module, class_name: str) -> frozenset[str]:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return frozenset(
            item.target.id
            for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        )
    return frozenset()


def _attribute_chain_names(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    current = node
    while isinstance(current, ast.Attribute):
        names.add(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        names.add(current.id)
    return frozenset(names)


def _assignment_attribute_targets(node: ast.AST) -> tuple[ast.Attribute, ...]:
    if isinstance(node, ast.Attribute):
        return (node,)
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(
            attribute
            for element in node.elts
            for attribute in _assignment_attribute_targets(element)
        )
    return ()


def _permission_state_mutations(tree: ast.Module) -> frozenset[str]:
    """返回绕过 PermissionController 的直接状态写入形状。"""

    mutations: set[str] = set()
    for node in ast.walk(tree):
        targets: tuple[ast.expr, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.AugAssign):
            targets = (node.target,)
        elif isinstance(node, ast.Delete):
            targets = tuple(node.targets)
        for target in targets:
            for attribute in _assignment_attribute_targets(target):
                if attribute.attr in {
                    "permission_mode",
                    "confirmed_values",
                    "confirmed_paths",
                    "_confirmed_paths",
                }:
                    mutations.add(attribute.attr)
                elif (
                    attribute.attr == "mode"
                    and _attribute_chain_names(attribute.value)
                    & _PERMISSION_STATE_BASE_NAMES
                ):
                    mutations.add("mode")

        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATING_SET_METHODS
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "confirmed_values"
        ):
            mutations.add(f"confirmed_values.{node.func.attr}")
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"mode", "confirmed_values"}
            and _attribute_chain_names(node.args[0]) & _PERMISSION_STATE_BASE_NAMES
        ):
            mutations.add(f"setattr:{node.args[1].value}")
    return frozenset(mutations)


def _plan_state_mutations(tree: ast.Module) -> frozenset[str]:
    """返回绕过 PlanRuntime 的直接 PlanState 写入形状。"""

    aliases = set(_PLAN_STATE_BASE_NAMES)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            target: ast.expr | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target = node.target
                value = node.value
            if not isinstance(target, ast.Name) or value is None:
                continue
            value_names = _attribute_chain_names(value)
            constructs_state = isinstance(value, ast.Call) and (
                (isinstance(value.func, ast.Name) and value.func.id == "PlanState")
                or (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "PlanState"
                )
            )
            if constructs_state or value_names & aliases:
                if target.id not in aliases:
                    aliases.add(target.id)
                    changed = True

    mutations: set[str] = set()
    for node in ast.walk(tree):
        targets: tuple[ast.expr, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.AugAssign):
            targets = (node.target,)
        elif isinstance(node, ast.Delete):
            targets = tuple(node.targets)
        for target in targets:
            for attribute in _assignment_attribute_targets(target):
                if (
                    attribute.attr in _PLAN_STATE_FIELDS
                    and _attribute_chain_names(attribute.value) & aliases
                ):
                    mutations.add(attribute.attr)

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _PLAN_STATE_FIELDS
            and _attribute_chain_names(node.args[0]) & aliases
        ):
            mutations.add(f"setattr:{node.args[1].value}")
    return frozenset(mutations)


def _attribute_references(tree: ast.Module, name: str) -> frozenset[str]:
    """返回属性访问，避免兼容镜像借不同宿主变量名回归。"""

    return frozenset(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == name
    )


def _named_constructor_count(tree: ast.Module, name: str) -> int:
    return sum(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
        for node in ast.walk(tree)
    )


def _session_identity_reset_count(tree: ast.Module) -> int:
    return sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reset"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr in {"session_state", "_session_state"}
        for node in ast.walk(tree)
    )


def _contains_string(tree: ast.AST, value: str) -> bool:
    return any(
        isinstance(node, ast.Constant) and node.value == value
        for node in ast.walk(tree)
    )


def _contains_attr_call(tree: ast.AST, attr: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        for node in ast.walk(tree)
    )


def _memory_index_write_sites(tree: ast.Module) -> frozenset[str]:
    sites: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if _contains_string(node, "MEMORY.md") and _contains_attr_call(
            node, "write_text"
        ):
            sites.add(node.name)
    return frozenset(sites)


def _removed_skill_command_symbols(tree: ast.Module) -> frozenset[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            name = node.name
        elif isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.alias):
            name = node.name
        elif isinstance(node, ast.Constant) and node.value == "/skill:":
            symbols.add("/skill:")
        if name in REMOVED_SKILL_COMMAND_SYMBOLS:
            symbols.add(name)
    return frozenset(symbols)


def _mcp_lifecycle_classes(tree: ast.Module) -> frozenset[str]:
    classes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name = node.name
        lowered = name.casefold()
        if name in MCP_LIFECYCLE_CLASS_NAMES or (
            "mcp" in lowered
            and any(
                marker in lowered
                for marker in ("client", "connection", "lifecycle", "manager")
            )
        ):
            classes.add(name)
    return frozenset(classes)


class _AttributeCallSites(ast.NodeVisitor):
    def __init__(self, attr: str) -> None:
        self._attr = attr
        self._class_names: list[str] = []
        self._function_names = ["<module>"]
        self.sites: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_names.append(node.name)
        self.generic_visit(node)
        self._class_names.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == self._attr:
            self.sites.add(self._current_site())
        self.generic_visit(node)

    def _visit_function(
        self,
        node: ast.AsyncFunctionDef | ast.FunctionDef,
    ) -> None:
        self._function_names.append(node.name)
        self.generic_visit(node)
        self._function_names.pop()

    def _current_site(self) -> str:
        parts = [*self._class_names, self._function_names[-1]]
        return ".".join(part for part in parts if part != "<module>")


def _attribute_call_sites(tree: ast.Module, attr: str) -> frozenset[str]:
    visitor = _AttributeCallSites(attr)
    visitor.visit(tree)
    return frozenset(visitor.sites)


def _provider_shim_exports(tree: ast.Module) -> tuple[str, ...]:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            return tuple(
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return ()


def _provider_shim_unexpected_statements(tree: ast.Module) -> tuple[str, ...]:
    unexpected: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module == "lion_code.core.provider":
                continue
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                continue
        unexpected.append(type(node).__name__)
    return tuple(unexpected)


class _SessionRecorderCalls(ast.NodeVisitor):
    def __init__(self) -> None:
        self._class_names: list[str] = []
        self._function_names = ["<module>"]
        self.sites: set[str] = set()
        self.attribute_calls: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_names.append(node.name)
        self.generic_visit(node)
        self._class_names.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "SessionRecorder":
            self.sites.add(self._current_site())
        elif (
            isinstance(node.func, ast.Attribute) and node.func.attr == "SessionRecorder"
        ):
            self.attribute_calls.add(self._current_site())
        self.generic_visit(node)

    def _visit_function(
        self,
        node: ast.AsyncFunctionDef | ast.FunctionDef,
    ) -> None:
        self._function_names.append(node.name)
        self.generic_visit(node)
        self._function_names.pop()

    def _current_site(self) -> str:
        parts = [*self._class_names, self._function_names[-1]]
        return ".".join(part for part in parts if part != "<module>")


def _session_recorder_calls(tree: ast.Module) -> _SessionRecorderCalls:
    visitor = _SessionRecorderCalls()
    visitor.visit(tree)
    return visitor


def _session_recorder_aliases(tree: ast.Module) -> frozenset[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "SessionRecorder" and alias.asname is not None:
                    aliases.add(alias.asname)
    return frozenset(aliases)


def _escaped_jsonl_writer_symbols(tree: ast.Module) -> frozenset[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            symbols.update(
                alias.name for alias in node.names if alias.name in JSONL_WRITER_SYMBOLS
            )
        elif isinstance(node, ast.Name) and node.id in JSONL_WRITER_SYMBOLS:
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in JSONL_WRITER_SYMBOLS:
            symbols.add(node.attr)
    return frozenset(symbols)


def _harness_mutation_calls(tree: ast.Module) -> frozenset[str]:
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in HARNESS_MUTATION_METHODS:
            calls.add(node.func.id)
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in HARNESS_MUTATION_METHODS
        ):
            calls.add(node.func.attr)
    return frozenset(calls)


def _agent_harness_references(tree: ast.Module) -> frozenset[str]:
    references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            references.update(
                alias.name for alias in node.names if alias.name == "AgentHarness"
            )
        elif isinstance(node, ast.Name) and node.id == "AgentHarness":
            references.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr == "AgentHarness":
            references.add(node.attr)
    return frozenset(references)


def _dynamic_import_calls(tree: ast.Module) -> frozenset[str]:
    """Detect ``importlib.import_module()`` and ``__import__()`` calls."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # importlib.import_module(...) or module.import_module(...)
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            calls.add("import_module")
        # import_module(...) (bare name, from importlib import import_module)
        elif isinstance(func, ast.Name) and func.id == "import_module":
            calls.add("import_module")
        # __import__(...)
        elif isinstance(func, ast.Name) and func.id == "__import__":
            calls.add("__import__")
    return frozenset(calls)


# Modules where session storage path literals may appear.
_SESSION_PATH_OWNERS = frozenset({"session_runtime/repository.py"})


def _string_literals_containing(tree: ast.Module, needle: str) -> frozenset[str]:
    """Return string literals in *tree* that contain *needle*."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and needle in node.value
        ):
            found.add(node.value)
    return frozenset(found)


def _assignment_targets(tree: ast.Module, name: str) -> frozenset[str]:
    """Return sites where *name* is assigned at module level."""
    sites: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    sites.add(target.id)
    return frozenset(sites)


def test_core_does_not_import_upper_runtime_layers() -> None:
    violations = _forbidden_imports(
        _source_files("core"),
        forbidden=_CORE.forbidden_roots,
    )

    assert not violations, f"Core imported an upper runtime layer: {violations}"


def test_provider_product_imports_are_core_or_local() -> None:
    violations = _unexpected_imports(
        _source_files("providers"),
        allowed=_PROVIDERS.allowed_roots,
    )

    assert not violations, f"Provider crossed its Core boundary: {violations}"


def test_tui_runtime_imports_stay_within_event_boundary() -> None:
    violations = _unexpected_imports(
        _source_files("tui"),
        allowed=_TUI.allowed_roots,
    )

    assert not violations, f"TUI bypassed application/core events: {violations}"


def test_providers_do_not_store_private_message_history() -> None:
    violations = {
        _source_key(path): sorted(_private_history_fields(_tree(path)))
        for path in _source_files("providers")
        if _private_history_fields(_tree(path))
    }

    assert not violations, (
        f"Provider private message history is forbidden: {violations}"
    )


def test_provider_state_fields_match_frozen_allowlist() -> None:
    """Provider self.* fields must match the frozen allowlist.

    Any new field requires updating PROVIDER_STATE_ALLOWLIST to force
    conscious review of whether it constitutes conversation history.
    """
    unregistered: list[str] = []
    drifted: dict[str, dict[str, list[str]]] = {}
    for path in _source_files("providers"):
        key = _source_key(path)
        actual = _self_fields(_tree(path))
        if not actual:
            continue
        if key not in PROVIDER_STATE_ALLOWLIST:
            unregistered.append(key)
            continue
        expected = PROVIDER_STATE_ALLOWLIST[key]
        added = actual - expected
        removed = expected - actual
        if added or removed:
            drifted[key] = {
                "added": sorted(added),
                "removed": sorted(removed),
            }
    assert not unregistered, (
        f"Provider files with state fields not in allowlist: {unregistered}"
    )
    assert not drifted, f"Provider state fields drifted from allowlist: {drifted}"


def test_legacy_message_paths_are_confined_to_read_only_migration() -> None:
    locations = _legacy_symbol_locations(_source_files())

    assert locations == {
        "_anthropic_messages": frozenset({"session_runtime/legacy.py"}),
        "_openai_messages": frozenset({"session_runtime/legacy.py"}),
    }


def test_global_ui_sink_symbol_is_absent() -> None:
    violations = {
        _source_key(path): sorted(_sink_symbols(_tree(path)))
        for path in _source_files()
        if _sink_symbols(_tree(path))
    }

    assert not violations, f"Process-global UI sinks are forbidden: {violations}"


def test_session_recorder_construction_sites_are_allowlisted() -> None:
    sites: dict[str, frozenset[str]] = {}
    aliases: dict[str, frozenset[str]] = {}
    attribute_calls: dict[str, frozenset[str]] = {}
    for path in _source_files():
        tree = _tree(path)
        calls = _session_recorder_calls(tree)
        if calls.sites:
            sites[_source_key(path)] = frozenset(calls.sites)
        if calls.attribute_calls:
            attribute_calls[_source_key(path)] = frozenset(calls.attribute_calls)
        if found_aliases := _session_recorder_aliases(tree):
            aliases[_source_key(path)] = found_aliases

    assert sites == SESSION_RECORDER_SITES
    assert not aliases, f"SessionRecorder aliases hide writer ownership: {aliases}"
    assert not attribute_calls, (
        "SessionRecorder must be constructed through the named ownership sites: "
        f"{attribute_calls}"
    )


def test_session_and_cancellation_state_have_single_owners() -> None:
    removed = {
        _source_key(path): sorted(
            _referenced_symbols(_tree(path), REMOVED_RUNTIME_SYMBOLS)
        )
        for path in _source_files()
        if _referenced_symbols(_tree(path), REMOVED_RUNTIME_SYMBOLS)
    }
    assert not removed, f"Removed runtime mirrors must not return: {removed}"

    context_fields = _class_annotated_fields(
        _tree(SOURCE_ROOT / "tooling" / "context.py"),
        "ToolContext",
    )
    assert {"session", "cancellation"} <= context_fields
    assert not {"session_id", "cancellation_fn"} & context_fields

    agent_fields = _self_fields(_tree(SOURCE_ROOT / "agent.py"))
    assert not {"session_id", "session_start_time", "_aborted"} & agent_fields

    identity_resets = {
        _source_key(path): _session_identity_reset_count(_tree(path))
        for path in _source_files()
        if _session_identity_reset_count(_tree(path))
    }
    assert identity_resets == {"session_lifecycle.py": 2}

    identity_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "SessionIdentityState")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "SessionIdentityState")
    }
    assert identity_constructors == {"agent.py": 1}

    execution_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "ExecutionControl")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "ExecutionControl")
    }
    assert execution_constructors == {"agent.py": 1}

    token_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "CancellationToken")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "CancellationToken")
    }
    assert token_constructors == {
        "core/harness.py": 1,
        "execution_control.py": 1,
    }


def test_permission_state_has_one_owner_and_live_read_ports() -> None:
    context_tree = _tree(SOURCE_ROOT / "tooling" / "context.py")
    context_fields = _class_annotated_fields(context_tree, "ToolContext")
    assert "permission" in context_fields
    assert not {"permission_mode", "confirmed_paths"} & context_fields
    assert _type_annotation_mentions(context_tree, "PermissionView")

    agent_fields = _self_fields(_tree(SOURCE_ROOT / "agent.py"))
    assert not {"permission_mode", "_confirmed_paths"} & agent_fields

    state_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "PermissionState")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "PermissionState")
    }
    controller_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "PermissionController")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "PermissionController")
    }
    assert state_constructors == {"agent.py": 1}
    assert controller_constructors == {"agent.py": 1}

    mutations = {
        _source_key(path): sorted(_permission_state_mutations(_tree(path)))
        for path in _source_files()
        if _source_key(path) != "permission_state.py"
        and _permission_state_mutations(_tree(path))
    }
    assert not mutations, f"PermissionState writes must use its Controller: {mutations}"

    set_mode_sites = {
        _source_key(path): sorted(_attribute_call_sites(_tree(path), "set_mode"))
        for path in _source_files()
        if _source_key(path) != "permission_state.py"
        and _attribute_call_sites(_tree(path), "set_mode")
    }
    assert set_mode_sites == {
        "plan_runtime.py": ["PlanRuntime._enter", "PlanRuntime._leave"]
    }

    middleware_tree = _tree(SOURCE_ROOT / "tooling" / "middleware.py")
    assert not _contains_attr_call(middleware_tree, "set_mode")
    assert _type_annotation_mentions(middleware_tree, "PermissionConfirmationSink")
    assert not _type_annotation_mentions(middleware_tree, "PermissionController")


def test_plan_state_has_one_owner_and_live_read_port() -> None:
    context_path = SOURCE_ROOT / "tooling" / "context.py"
    context_tree = _tree(context_path)
    context_fields = _class_annotated_fields(context_tree, "ToolContext")
    assert "plan" in context_fields
    assert "plan_file_path" not in context_fields
    assert _type_annotation_mentions(context_tree, "PlanView")

    plan_tree = _tree(SOURCE_ROOT / "plan_runtime.py")
    assert _class_annotated_fields(plan_tree, "PlanState") == _PLAN_STATE_FIELDS

    agent_fields = _self_fields(_tree(SOURCE_ROOT / "agent.py"))
    assert not _REMOVED_AGENT_PLAN_SYMBOLS & agent_fields
    removed_symbols = {
        _source_key(path): sorted(
            _referenced_symbols(_tree(path), _REMOVED_AGENT_PLAN_SYMBOLS)
        )
        for path in _source_files()
        if _referenced_symbols(_tree(path), _REMOVED_AGENT_PLAN_SYMBOLS)
    }
    assert not removed_symbols, (
        f"Removed Plan mirrors must not return: {removed_symbols}"
    )

    path_mirrors = {
        _source_key(path): sorted(_attribute_references(_tree(path), "plan_file_path"))
        for path in _source_files()
        if _attribute_references(_tree(path), "plan_file_path")
    }
    assert not path_mirrors, (
        f"ToolContext Plan path mirrors must not return: {path_mirrors}"
    )

    host_tree = _tree(SOURCE_ROOT / "agent_runtime.py")
    host_fields = _class_annotated_fields(host_tree, "SessionStateHost")
    assert "plan" in host_fields
    assert not _REMOVED_AGENT_PLAN_SYMBOLS & host_fields

    lifecycle_tree = _tree(SOURCE_ROOT / "session_lifecycle.py")
    lifecycle_prompt_symbols = frozenset(
        {
            "_base_system_prompt",
            "_system_prompt",
            "_build_prompt",
            "_build_plan_mode_prompt",
            "_generate_file_path",
        }
    )
    assert not _referenced_symbols(lifecycle_tree, lifecycle_prompt_symbols)

    state_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "PlanState")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "PlanState")
    }
    runtime_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "PlanRuntime")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "PlanRuntime")
    }
    assert state_constructors == {"agent.py": 1}
    assert runtime_constructors == {"agent.py": 1}

    mutations = {
        _source_key(path): sorted(_plan_state_mutations(_tree(path)))
        for path in _source_files()
        if _source_key(path) != "plan_runtime.py" and _plan_state_mutations(_tree(path))
    }
    assert not mutations, f"PlanState writes must stay in PlanRuntime: {mutations}"

    middleware_source = (SOURCE_ROOT / "tooling" / "middleware.py").read_text(
        encoding="utf-8"
    )
    assert "context.plan_file_path" not in middleware_source
    assert middleware_source.count("context.plan.file_path") == 2


def test_jsonl_writer_primitives_do_not_escape_persistence_boundary() -> None:
    violations = {
        _source_key(path): sorted(_escaped_jsonl_writer_symbols(_tree(path)))
        for path in _source_files()
        if not _source_key(path).startswith(("core/", "session_runtime/"))
        and _escaped_jsonl_writer_symbols(_tree(path))
    }

    assert not violations, f"JSONL writer bypassed SessionRecorder: {violations}"


def test_session_storage_path_literals_stay_in_repository() -> None:
    """``.jsonl`` path literals must only appear in ``session_runtime/``."""
    violations = {
        _source_key(path): sorted(_string_literals_containing(_tree(path), ".jsonl"))
        for path in _source_files()
        if _source_key(path) not in _SESSION_PATH_OWNERS
        and _string_literals_containing(_tree(path), ".jsonl")
    }
    assert not violations, (
        f"Session storage path literals must stay in session_runtime/repository: "
        f"{violations}"
    )


def test_session_dir_constant_has_single_definition() -> None:
    """``SESSION_DIR`` must only be defined in ``session_runtime/repository.py``."""
    sites: dict[str, frozenset[str]] = {}
    for path in _source_files():
        found = _assignment_targets(_tree(path), "SESSION_DIR")
        if found:
            sites[_source_key(path)] = found
    assert sites == {"session_runtime/repository.py": frozenset({"SESSION_DIR"})}, (
        f"SESSION_DIR must have a single owner: {sites}"
    )


def test_dynamic_imports_are_allowlisted() -> None:
    """``importlib.import_module`` and ``__import__`` bypass static analysis.

    They must not appear outside the explicit allowlist.
    """
    violations = {
        _source_key(path): sorted(_dynamic_import_calls(_tree(path)))
        for path in _source_files()
        if _source_key(path) not in DYNAMIC_IMPORT_ALLOWLIST
        and _dynamic_import_calls(_tree(path))
    }
    assert not violations, (
        f"Dynamic imports bypass static architecture checks: {violations}. "
        f"Add to DYNAMIC_IMPORT_ALLOWLIST if intentional."
    )


def test_memory_overlay_code_cannot_mutate_harness_messages() -> None:
    paths = (
        *_source_files("memory_runtime"),
        SOURCE_ROOT / "session_memory_coordinator.py",
    )
    harness_references = {
        _source_key(path): sorted(_agent_harness_references(_tree(path)))
        for path in paths
        if _agent_harness_references(_tree(path))
    }
    mutations = {
        _source_key(path): sorted(_harness_mutation_calls(_tree(path)))
        for path in paths
        if _harness_mutation_calls(_tree(path))
    }

    assert not harness_references, (
        f"Memory Overlay code must not own an AgentHarness: {harness_references}"
    )
    assert not mutations, (
        "Memory Overlay code must return temporary projections, not mutate Core: "
        f"{mutations}"
    )


def _type_annotation_mentions(tree: ast.Module, name: str) -> bool:
    """Check whether *name* appears in any type annotation in *tree*."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


def test_memory_layer_does_not_reference_agent_harness_in_types() -> None:
    """Memory layer type annotations must not mention ``AgentHarness``.

    The ``ReadOnlyMessageSource`` Protocol replaces direct Harness access;
    type-level references to ``AgentHarness`` would bypass that boundary.
    """
    paths = (
        *_source_files("memory_runtime"),
        SOURCE_ROOT / "session_memory_coordinator.py",
    )
    violations = {
        _source_key(path): ["AgentHarness"]
        for path in paths
        if _type_annotation_mentions(_tree(path), "AgentHarness")
    }
    assert not violations, (
        f"Memory layer must not reference AgentHarness in type annotations: "
        f"{violations}"
    )


def test_memory_index_has_one_authoritative_definition() -> None:
    definitions = {
        _source_key(path): sorted(
            _defined_symbols(_tree(path), MEMORY_INDEX_REBUILD_SYMBOLS)
        )
        for path in _source_files()
        if _defined_symbols(_tree(path), MEMORY_INDEX_REBUILD_SYMBOLS)
    }
    write_sites = {
        _source_key(path): sorted(_memory_index_write_sites(_tree(path)))
        for path in _source_files()
        if _memory_index_write_sites(_tree(path))
    }

    assert definitions == {
        "memory.py": ["_update_memory_index", "rebuild_memory_index_if_needed"]
    }
    assert write_sites == {"memory.py": ["_update_memory_index"]}, (
        f"MEMORY.md index writes must stay inside memory.py: {write_sites}"
    )


def test_removed_skill_command_symbols_do_not_return() -> None:
    violations = {
        _source_key(path): sorted(_removed_skill_command_symbols(_tree(path)))
        for path in _source_files()
        if _removed_skill_command_symbols(_tree(path))
    }

    assert not violations, f"旧 /skill: 半成品入口不得重新进入产品代码: {violations}"


def test_mcp_lifecycle_management_has_single_owner() -> None:
    lifecycle_classes = {
        _source_key(path): sorted(_mcp_lifecycle_classes(_tree(path)))
        for path in _source_files()
        if _mcp_lifecycle_classes(_tree(path))
    }
    disconnect_calls = {
        _source_key(path): sorted(_attribute_call_sites(_tree(path), "disconnect_all"))
        for path in _source_files()
        if _attribute_call_sites(_tree(path), "disconnect_all")
    }

    assert lifecycle_classes == {"mcp_client.py": ["McpConnection", "McpManager"]}
    assert disconnect_calls == {"tooling/environment.py": ["ToolEnvironment.close"]}, (
        "MCP disconnect lifecycle must remain owned by ToolEnvironment: "
        f"{disconnect_calls}"
    )


def test_provider_shim_remains_reexport_only() -> None:
    tree = _tree(SOURCE_ROOT / "providers" / "provider.py")

    assert _provider_shim_exports(tree) == PROVIDER_SHIM_EXPORTS
    assert _provider_shim_unexpected_statements(tree) == ()


def test_scanners_reject_reintroduced_boundary_patterns() -> None:
    provider = ast.parse(
        "class Provider:\n"
        "    def __init__(self) -> None:\n"
        "        self._messages = []\n"
        "        setattr(self, '_history', [])\n"
        "        self._conversation = []\n"
        "        self._transcript = []\n"
        "        self._turns = []\n"
    )
    sink = ast.parse("def configure(ui):\n    return getattr(ui, 'set_sink')\n")
    writer = ast.parse("def create_writer():\n    return SessionRecorder()\n")
    writer_alias = ast.parse(
        "from lion_code.session_runtime import SessionRecorder as Writer\n"
    )
    writer_attribute = ast.parse(
        "def create_writer(session_runtime):\n"
        "    return session_runtime.SessionRecorder()\n"
    )
    legacy = ast.parse(
        "def convert(row):\n    return getattr(row, '_openai_messages')\n"
    )
    jsonl_writer = ast.parse("from lion_code.core.session import JsonlSessionStorage\n")
    memory = ast.parse("def inject(runtime):\n    runtime.replace_messages([])\n")
    memory_owner = ast.parse("from lion_code.core import AgentHarness\n")
    memory_index_writer = ast.parse(
        "def rebuild(root):\n    (root / 'MEMORY.md').write_text('')\n"
    )
    old_skill = ast.parse("def parse_skill_invocation():\n    return '/skill:'\n")
    mcp_lifecycle = ast.parse("class McpClient:\n    pass\n")
    mcp_disconnect = ast.parse("def close(manager):\n    manager.disconnect_all()\n")
    dynamic_importlib = ast.parse(
        "import importlib\ndef load(name):\n    return importlib.import_module(name)\n"
    )
    dynamic_builtin = ast.parse("def load(name):\n    return __import__(name)\n")
    jsonl_literal = ast.parse("path = 'session.jsonl'\n")
    session_dir_assign = ast.parse("SESSION_DIR = Path.home() / 'sessions'\n")
    permission_mutation = ast.parse(
        "def bypass(state):\n"
        "    state.mode = 'plan'\n"
        "    state.confirmed_values.add('value')\n"
        "    state.confirmed_values.update({'other'})\n"
        "    del state.confirmed_values\n"
    )
    permission_mirror = ast.parse(
        "class Agent:\n    def change(self):\n        self.permission_mode = 'plan'\n"
    )
    plan_mutation = ast.parse(
        "def bypass(plan_state):\n"
        "    plan_state.status = 'active'\n"
        "    plan_state.file_path = path\n"
        "    renamed = plan_state\n"
        "    renamed.previous_permission_mode = 'default'\n"
        "    setattr(plan_state, 'pending_context_reset', 'summary')\n"
    )
    plan_path_mirror = ast.parse(
        "def sync(alias):\n    alias.plan_file_path = 'plan.md'\n"
    )

    assert _private_history_fields(provider) == frozenset(
        {
            "_conversation",
            "_history",
            "_messages",
            "_transcript",
            "_turns",
        }
    )
    assert _sink_symbols(sink) == frozenset({"set_sink"})
    assert _session_recorder_calls(writer).sites == {"create_writer"}
    assert _session_recorder_aliases(writer_alias) == frozenset({"Writer"})
    assert _session_recorder_calls(writer_attribute).attribute_calls == {
        "create_writer"
    }
    assert _legacy_symbols(legacy) == frozenset({"_openai_messages"})
    assert _escaped_jsonl_writer_symbols(jsonl_writer) == frozenset(
        {"JsonlSessionStorage"}
    )
    assert _harness_mutation_calls(memory) == frozenset({"replace_messages"})
    assert _agent_harness_references(memory_owner) == frozenset({"AgentHarness"})
    assert _memory_index_write_sites(memory_index_writer) == frozenset({"rebuild"})
    assert _removed_skill_command_symbols(old_skill) == frozenset(
        {"/skill:", "parse_skill_invocation"}
    )
    assert _mcp_lifecycle_classes(mcp_lifecycle) == frozenset({"McpClient"})
    assert _attribute_call_sites(mcp_disconnect, "disconnect_all") == frozenset(
        {"close"}
    )
    assert _dynamic_import_calls(dynamic_importlib) == frozenset({"import_module"})
    assert _dynamic_import_calls(dynamic_builtin) == frozenset({"__import__"})
    assert _string_literals_containing(jsonl_literal, ".jsonl") == frozenset(
        {"session.jsonl"}
    )
    assert _assignment_targets(session_dir_assign, "SESSION_DIR") == frozenset(
        {"SESSION_DIR"}
    )
    assert _permission_state_mutations(permission_mutation) == frozenset(
        {
            "mode",
            "confirmed_values",
            "confirmed_values.add",
            "confirmed_values.update",
        }
    )
    assert _permission_state_mutations(permission_mirror) == frozenset(
        {"permission_mode"}
    )
    assert _plan_state_mutations(plan_mutation) == frozenset(
        {
            "status",
            "file_path",
            "previous_permission_mode",
            "setattr:pending_context_reset",
        }
    )
    assert _attribute_references(plan_path_mirror, "plan_file_path") == frozenset(
        {"plan_file_path"}
    )


# ---------------------------------------------------------------------------
# Unified boundary validation
# ---------------------------------------------------------------------------


def _external_package_imports(
    tree: ast.Module, packages: frozenset[str]
) -> frozenset[str]:
    """Return top-level external package imports matching *packages*."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in packages:
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in packages:
                found.add(node.module)
    return frozenset(found)


def test_all_roots_matches_filesystem() -> None:
    """``ALL_ROOTS`` in ``_boundaries.py`` must match the actual source tree."""
    from _boundaries import _discover_all_roots

    discovered = _discover_all_roots()
    assert ALL_ROOTS == discovered, (
        f"ALL_ROOTS is stale; expected {sorted(discovered)}, got {sorted(ALL_ROOTS)}"
    )


def test_import_linter_config_matches_boundaries() -> None:
    """Every import-linter contract in ``pyproject.toml`` must match the
    corresponding ``Boundary`` definition in ``_boundaries.py``."""
    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    lint_by_name: dict[str, dict] = {c["name"]: c for c in contracts}

    assert set(lint_by_name) == {b.contract_name for b in BOUNDARIES}, (
        f"Contract names mismatch:\n"
        f"  import-linter: {sorted(lint_by_name)}\n"
        f"  boundaries:    {sorted(b.contract_name for b in BOUNDARIES)}"
    )

    for boundary in BOUNDARIES:
        contract = lint_by_name[boundary.contract_name]

        assert contract["type"] == "forbidden", (
            f"{boundary.contract_name}: expected type 'forbidden'"
        )
        assert contract["source_modules"] == [boundary.source_package], (
            f"{boundary.contract_name}: source_modules mismatch"
        )

        expected_forbidden = sorted(boundary.import_linter_forbidden_modules)
        actual_forbidden = sorted(contract["forbidden_modules"])
        assert actual_forbidden == expected_forbidden, (
            f"{boundary.contract_name}: forbidden_modules drift\n"
            f"  expected ({len(expected_forbidden)}): {expected_forbidden}\n"
            f"  actual   ({len(actual_forbidden)}): {actual_forbidden}"
        )

        expected_indirect = "True" if boundary.allow_indirect else "False"
        assert contract.get("allow_indirect_imports", "False") == expected_indirect, (
            f"{boundary.contract_name}: allow_indirect_imports mismatch"
        )


def test_production_code_does_not_import_tests_or_benchmarks() -> None:
    """Production code must not import from ``tests`` or ``benchmarks``."""
    targets = _PRODUCTION.forbidden
    assert targets is not None
    violations = {
        _source_key(path): sorted(_external_package_imports(_tree(path), targets))
        for path in _source_files()
        if _external_package_imports(_tree(path), targets)
    }
    assert not violations, (
        f"Production code must not import tests/benchmarks: {violations}"
    )


# ---------------------------------------------------------------------------
# Behavioral / runtime boundary tests
# ---------------------------------------------------------------------------


async def test_provider_does_not_retain_conversation_across_requests() -> None:
    """A Provider must not retain or mix conversation messages between requests.

    This is the runtime complement to the AST keyword/allowlist scans: it
    verifies the *behavior* regardless of field names.
    """
    from lion_code.core.messages import AssistantMessage, UserMessage
    from lion_code.core.provider_events import AssistantDoneEvent
    from lion_code.providers.fake import FakeProvider

    provider = FakeProvider(
        [
            [
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="test", content="first"),
                )
            ],
            [
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="test", content="second"),
                )
            ],
        ]
    )

    messages_1 = [UserMessage(content="hello")]
    messages_2 = [UserMessage(content="world")]

    async for _ in provider.stream_response(
        model="test",
        system="",
        messages=messages_1,
        tools=[],
    ):
        pass

    async for _ in provider.stream_response(
        model="test",
        system="",
        messages=messages_2,
        tools=[],
    ):
        pass

    # Each call saw its own messages, no cross-contamination.
    assert len(provider.calls) == 2
    assert [m.content for m in provider.calls[0][2]] == ["hello"]
    assert [m.content for m in provider.calls[1][2]] == ["world"]

    # Input lists were not mutated by the provider.
    assert [m.content for m in messages_1] == ["hello"]
    assert [m.content for m in messages_2] == ["world"]


async def test_single_conversation_produces_one_jsonl_file() -> None:
    """One conversation must produce exactly one session JSONL file.

    No module outside the SessionRecorder / JsonlSessionStorage boundary
    may create additional .jsonl files in the session directory.
    """
    import tempfile

    from lion_code.core.messages import AssistantMessage, UserMessage
    from lion_code.core.session import JsonlSessionStorage
    from lion_code.session_runtime import SessionRecorder

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        storage = JsonlSessionStorage(tmp_path / "s1.jsonl")
        recorder = SessionRecorder(
            session_id="s1",
            model="test",
            thinking_level="disabled",
            cwd=tmp_path,
            storage=storage,
        )

        await recorder.record_message(UserMessage(content="hello"))
        await recorder.record_message(AssistantMessage(model="test", content="hi"))
        await recorder.record_message(UserMessage(content="bye"))
        await recorder.record_message(AssistantMessage(model="test", content="bye"))

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        assert len(jsonl_files) == 1, (
            f"Expected 1 JSONL file, found {len(jsonl_files)}: {jsonl_files}"
        )

        entries = await storage.read_all()
        message_entries = [e for e in entries if e.type == "message"]
        assert len(message_entries) == 4
