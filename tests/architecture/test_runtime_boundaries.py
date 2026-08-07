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
PROVIDER_SHIM_EXPORTS = ("CancellationToken", "ModelProvider")

# Dynamic import calls that bypass static import analysis (import-linter / AST).
DYNAMIC_IMPORT_CALLS = frozenset({"import_module", "__import__"})
# Modules allowed to use dynamic imports.  Currently empty — adding a dynamic
# import requires consciously extending this allowlist.
DYNAMIC_IMPORT_ALLOWLIST: frozenset[str] = frozenset()


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
