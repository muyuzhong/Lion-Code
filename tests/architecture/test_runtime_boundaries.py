from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

CORE_FORBIDDEN_ROOTS = frozenset({"providers", "tooling", "application", "tui"})
PROVIDER_ALLOWED_ROOTS = frozenset({"core", "providers"})
TUI_ALLOWED_ROOTS = frozenset(
    {"application", "config", "core", "prompt", "tui", "version"}
)
LEGACY_MESSAGE_SYMBOLS = frozenset({"_anthropic_messages", "_openai_messages"})
HARNESS_MUTATION_METHODS = frozenset({"clear_queues", "follow_up", "replace_messages"})
SESSION_RECORDER_SITES = {
    "agent.py": frozenset({"Agent._migrate_legacy_core_session"}),
    "agent_runtime.py": frozenset({"AgentRuntimeCoordinator.reset_core_observers"}),
}
JSONL_WRITER_SYMBOLS = frozenset({"JsonlSessionStorage", "entry_to_json_line"})


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


def _private_history_fields(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        field
        for field in _self_fields(tree)
        if "messages" in field.casefold() or "history" in field.casefold()
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


def test_core_does_not_import_upper_runtime_layers() -> None:
    violations = _forbidden_imports(
        _source_files("core"),
        forbidden=CORE_FORBIDDEN_ROOTS,
    )

    assert not violations, f"Core imported an upper runtime layer: {violations}"


def test_provider_product_imports_are_core_or_local() -> None:
    violations = _unexpected_imports(
        _source_files("providers"),
        allowed=PROVIDER_ALLOWED_ROOTS,
    )

    assert not violations, f"Provider crossed its Core boundary: {violations}"


def test_tui_runtime_imports_stay_within_event_boundary() -> None:
    violations = _unexpected_imports(
        _source_files("tui"),
        allowed=TUI_ALLOWED_ROOTS,
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


def test_scanners_reject_reintroduced_boundary_patterns() -> None:
    provider = ast.parse(
        "class Provider:\n"
        "    def __init__(self) -> None:\n"
        "        self._messages = []\n"
        "        setattr(self, '_history', [])\n"
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

    assert _private_history_fields(provider) == frozenset({"_history", "_messages"})
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
