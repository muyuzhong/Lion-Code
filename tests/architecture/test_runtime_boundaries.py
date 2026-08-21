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
_SUPERVISOR = BOUNDARIES[1]
_COMPOSITION = BOUNDARIES[2]
_META_AGENT = BOUNDARIES[3]
_PROVIDERS = BOUNDARIES[4]
_APPLICATION = BOUNDARIES[5]
_TUI = BOUNDARIES[6]
_SERVER = BOUNDARIES[7]
_CAPABILITIES = BOUNDARIES[8]
_PRODUCTION = BOUNDARIES[9]

LEGACY_MESSAGE_SYMBOLS = frozenset({"_anthropic_messages", "_openai_messages"})
HARNESS_MUTATION_METHODS = frozenset({"clear_queues", "follow_up", "replace_messages"})
SESSION_RECORDER_SITES = {
    "adapters/coding_session_backend.py": frozenset(
        {"CodingSessionBackendAdapter._migrate_legacy_core_session"}
    ),
    "runtime/session.py": frozenset({"SessionRuntime._reset_recorder"}),
}
JSONL_WRITER_SYMBOLS = frozenset({"JsonlSessionStorage", "entry_to_json_line"})
REMOVED_SKILL_COMMAND_SYMBOLS = frozenset(
    {
        "SkillInvocation",
        "expand_skill_command",
        "format_skill_invocation",
        "parse_skill_invocation",
    }
)
# PR7b 删除的外部工具协议 token；拼接构造以避免测试自身成为残留。
_REMOVED_PROTOCOL_TOKEN = "m" + "cp"
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
REMOVED_USAGE_SYMBOLS = frozenset(
    {
        "UsageStateHost",
        "UsageTotals",
        "_check_budget",
        "_get_current_cost_usd",
        "current_turns",
        "last_api_call_time",
        "last_input_token_count",
        "sync_core_usage",
        "sync_usage_from_observer",
        "total_cache_creation_tokens",
        "total_cache_read_tokens",
        "total_input_tokens",
        "total_output_tokens",
    }
)
_USAGE_LEDGER_FIELDS = frozenset(
    {
        "_cache_read_tokens",
        "_cache_write_tokens",
        "_input_tokens",
        "_last_prompt_tokens",
        "_last_response_at",
        "_output_tokens",
        "_responses",
        "_turns",
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
            "_content_parts",
            "_finish_reason",
            "_owns_client",
            "_thinking_parts",
            "_thinking_signature",
            "_tool_builders",
            "_usage",
            "arguments_parts",
            "emitted_content",
            "fatal",
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
            "_thinking_parts",
            "_thinking_signature",
            "_tool_call_builders",
            "_usage",
            "arguments_parts",
            "emitted_content",
            "fatal",
            "id",
            "name",
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


def _attribute_mutations(
    tree: ast.Module,
    names: frozenset[str],
) -> frozenset[str]:
    """返回指定属性的赋值、删除或动态属性写入。"""

    mutation_call_aliases: dict[str, int] = {"delattr": 1, "setattr": 1}
    delete_call_aliases = {"delattr"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "builtins":
                for imported in node.names:
                    if imported.name not in {"delattr", "setattr"}:
                        continue
                    local_name = imported.asname or imported.name
                    if local_name not in mutation_call_aliases:
                        mutation_call_aliases[local_name] = 1
                        changed = True
                    if (
                        imported.name == "delattr"
                        and local_name not in delete_call_aliases
                    ):
                        delete_call_aliases.add(local_name)
                        changed = True
                continue

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

            field_arg_index: int | None = None
            if isinstance(value, ast.Name):
                field_arg_index = mutation_call_aliases.get(value.id)
            elif isinstance(value, ast.Attribute) and value.attr in {
                "__delattr__",
                "__setattr__",
                "delattr",
                "setattr",
            }:
                field_arg_index = (
                    1
                    if isinstance(value.value, ast.Name)
                    and value.value.id in {"builtins", "object"}
                    else 0
                )
            if (
                field_arg_index is not None
                and mutation_call_aliases.get(target.id) != field_arg_index
            ):
                mutation_call_aliases[target.id] = field_arg_index
                changed = True
            if (
                (isinstance(value, ast.Name) and value.id in delete_call_aliases)
                or (isinstance(value, ast.Attribute) and "delattr" in value.attr)
            ) and target.id not in delete_call_aliases:
                delete_call_aliases.add(target.id)
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
                if attribute.attr in names:
                    mutations.add(attribute.attr)
        if not isinstance(node, ast.Call):
            continue
        field_arg_index: int | None = None
        operation = "setattr"
        if isinstance(node.func, ast.Name):
            field_arg_index = mutation_call_aliases.get(node.func.id)
            if node.func.id in delete_call_aliases:
                operation = "delattr"
        elif isinstance(node.func, ast.Attribute) and node.func.attr in {
            "__delattr__",
            "__setattr__",
            "delattr",
            "setattr",
        }:
            operation = "delattr" if "delattr" in node.func.attr else "setattr"
            field_arg_index = (
                1
                if isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"builtins", "object"}
                else 0
            )
        if field_arg_index is None or len(node.args) <= field_arg_index:
            continue
        field_arg = node.args[field_arg_index]
        if isinstance(field_arg, ast.Constant) and field_arg.value in names:
            mutations.add(f"{operation}:{field_arg.value}")
    return frozenset(mutations)


def _named_constructor_count(tree: ast.Module, name: str) -> int:
    aliases = {name}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for imported in node.names:
                    if imported.name != name:
                        continue
                    local_name = imported.asname or imported.name
                    if local_name not in aliases:
                        aliases.add(local_name)
                        changed = True
                continue

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
            is_alias = (isinstance(value, ast.Name) and value.id in aliases) or (
                isinstance(value, ast.Attribute) and value.attr == name
            )
            if is_alias and target.id not in aliases:
                aliases.add(target.id)
                changed = True

    return sum(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in aliases)
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


def _contains_attr_call(tree: ast.AST, attr: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        for node in ast.walk(tree)
    )


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


def test_composition_does_not_import_product_facades_or_interfaces() -> None:
    composition_core = tuple(
        path
        for path in _source_files("composition")
        if _source_key(path) != "composition/full_product.py"
    )
    violations = _forbidden_imports(
        composition_core,
        forbidden=_COMPOSITION.forbidden_roots,
    )

    assert not violations, f"Composition imported an upper product layer: {violations}"

    bootstrap_violations = _forbidden_imports(
        [SOURCE_ROOT / "composition" / "full_product.py"],
        forbidden=_COMPOSITION.forbidden_roots - {"meta_agent"},
    )
    assert not bootstrap_violations, (
        "Full product bootstrap imported an unrelated upper layer: "
        f"{bootstrap_violations}"
    )


def test_meta_agent_does_not_import_features_or_interfaces() -> None:
    violations = _forbidden_imports(
        [SOURCE_ROOT / "meta_agent.py"],
        forbidden=_META_AGENT.forbidden_roots,
    )

    assert not violations, f"MetaAgent imported a product feature: {violations}"


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


def test_server_runtime_imports_stay_within_event_boundary() -> None:
    violations = _unexpected_imports(
        _source_files("server"),
        allowed=_SERVER.allowed_roots,
    )

    assert not violations, f"Server bypassed application/core events: {violations}"


def test_capabilities_do_not_import_agent_host_or_frontend() -> None:
    violations = _forbidden_imports(
        _source_files("capabilities"),
        forbidden=_CAPABILITIES.forbidden_roots,
    )

    assert not violations, (
        f"Capability SPI must not depend on Agent host / Application / TUI: "
        f"{violations}"
    )


_CAPABILITY_ANTIPATTERN_SYMBOLS = frozenset(
    {
        "CapabilityContext",
        "ServiceLocator",
        "AgentCapability",
    }
)


def test_capabilities_do_not_reference_agent_harness() -> None:
    """Capability SPI must not reference ``AgentHarness`` in any form."""
    violations = {
        _source_key(path): sorted(_agent_harness_references(_tree(path)))
        for path in _source_files("capabilities")
        if _agent_harness_references(_tree(path))
    }
    assert not violations, (
        f"Capability SPI must not reference AgentHarness: {violations}"
    )


def test_capabilities_do_not_define_service_locator_or_god_context() -> None:
    """Capability SPI must not define CapabilityContext, ServiceLocator, or a
    monolithic AgentCapability interface."""
    violations = {
        _source_key(path): sorted(
            _defined_symbols(_tree(path), _CAPABILITY_ANTIPATTERN_SYMBOLS)
        )
        for path in _source_files("capabilities")
        if _defined_symbols(_tree(path), _CAPABILITY_ANTIPATTERN_SYMBOLS)
    }
    assert not violations, (
        f"Capability SPI must not define god-context or service-locator types: "
        f"{violations}"
    )


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

    meta_agent_fields = _self_fields(_tree(SOURCE_ROOT / "meta_agent.py"))
    assert not {"session_id", "session_start_time", "_aborted"} & meta_agent_fields

    identity_resets = {
        _source_key(path): _session_identity_reset_count(_tree(path))
        for path in _source_files()
        if _session_identity_reset_count(_tree(path))
    }
    assert identity_resets == {"runtime/session.py": 2}

    identity_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "SessionIdentityState")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "SessionIdentityState")
    }
    assert identity_constructors == {"composition/agent_builder.py": 1}

    execution_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "ExecutionControl")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "ExecutionControl")
    }
    assert execution_constructors == {"composition/agent_builder.py": 1}

    token_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "CancellationToken")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "CancellationToken")
    }
    assert token_constructors == {
        "core/harness.py": 1,
        "runtime/execution.py": 1,
    }


def test_usage_state_has_one_owner_and_command_only_writes() -> None:
    removed = {
        _source_key(path): sorted(
            _referenced_symbols(_tree(path), REMOVED_USAGE_SYMBOLS)
        )
        for path in _source_files()
        if _referenced_symbols(_tree(path), REMOVED_USAGE_SYMBOLS)
    }
    assert not removed, f"Removed Usage mirrors must not return: {removed}"

    meta_agent_fields = _self_fields(_tree(SOURCE_ROOT / "meta_agent.py"))
    assert not REMOVED_USAGE_SYMBOLS & meta_agent_fields
    assert "_usage_observer" not in meta_agent_fields

    ledger_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "UsageLedger")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "UsageLedger")
    }
    policy_constructors = {
        _source_key(path): _named_constructor_count(_tree(path), "BudgetPolicy")
        for path in _source_files()
        if _named_constructor_count(_tree(path), "BudgetPolicy")
    }
    assert ledger_constructors == {"composition/agent_builder.py": 1}
    assert policy_constructors == {"composition/agent_builder.py": 1}

    observer_fields = _self_fields(_tree(SOURCE_ROOT / "observers" / "usage.py"))
    assert observer_fields == {"_ledger"}

    external_mutations = {
        _source_key(path): sorted(
            _attribute_mutations(_tree(path), _USAGE_LEDGER_FIELDS)
        )
        for path in _source_files()
        if _source_key(path) != "usage.py"
        and _attribute_mutations(_tree(path), _USAGE_LEDGER_FIELDS)
    }
    assert not external_mutations, (
        f"UsageLedger fields must only be written in usage.py: {external_mutations}"
    )

    record_model_sites = {
        _source_key(path): sorted(
            _attribute_call_sites(_tree(path), "record_model_usage")
        )
        for path in _source_files()
        if _attribute_call_sites(_tree(path), "record_model_usage")
    }
    record_child_sites = {
        _source_key(path): sorted(
            _attribute_call_sites(_tree(path), "record_child_usage")
        )
        for path in _source_files()
        if _attribute_call_sites(_tree(path), "record_child_usage")
    }
    record_turn_sites = {
        _source_key(path): sorted(_attribute_call_sites(_tree(path), "record_turn"))
        for path in _source_files()
        if _attribute_call_sites(_tree(path), "record_turn")
    }
    reset_sites = {
        _source_key(path): sorted(_attribute_call_sites(_tree(path), "reset"))
        for path in _source_files()
        if _source_key(path) == "runtime/agent.py"
        and _attribute_call_sites(_tree(path), "reset")
    }
    context_reset_sites = {
        _source_key(path): sorted(
            _attribute_call_sites(_tree(path), "reset_context_tracking")
        )
        for path in _source_files()
        if _attribute_call_sites(_tree(path), "reset_context_tracking")
    }
    assert record_model_sites == {"observers/usage.py": ["UsageObserver.handle"]}
    assert record_child_sites == {
        "capabilities/subagent/runtime.py": ["SubagentExecutor._run_child"],
    }
    assert record_turn_sites == {
        "runtime/agent.py": ["AgentRuntime.before_core_tool_calls"]
    }
    assert reset_sites == {"runtime/agent.py": ["AgentRuntime.reset_session_usage"]}
    assert context_reset_sites == {
        "runtime/agent.py": ["AgentRuntime.compact_if_needed"]
    }


def test_permission_state_has_one_owner_and_live_read_ports() -> None:
    context_tree = _tree(SOURCE_ROOT / "tooling" / "context.py")
    context_fields = _class_annotated_fields(context_tree, "ToolContext")
    assert "permission" in context_fields
    assert not {"permission_mode", "confirmed_paths"} & context_fields
    assert _type_annotation_mentions(context_tree, "PermissionView")

    meta_agent_fields = _self_fields(_tree(SOURCE_ROOT / "meta_agent.py"))
    assert not {"permission_mode", "_confirmed_paths"} & meta_agent_fields

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
    assert state_constructors == {"composition/agent_builder.py": 1}
    assert controller_constructors == {"composition/agent_builder.py": 1}

    mutations = {
        _source_key(path): sorted(_permission_state_mutations(_tree(path)))
        for path in _source_files()
        if _source_key(path) != "permission_state.py"
        and _permission_state_mutations(_tree(path))
    }
    assert not mutations, f"PermissionState writes must use its Controller: {mutations}"

    # PR4：Plan 不再是 Permission 模式，没有任何业务方调用 set_mode。
    set_mode_sites = {
        _source_key(path): sorted(_attribute_call_sites(_tree(path), "set_mode"))
        for path in _source_files()
        if _source_key(path) != "permission_state.py"
        and _attribute_call_sites(_tree(path), "set_mode")
    }
    assert not set_mode_sites, (
        f"set_mode 只允许在 permission_state.py 内部出现: {set_mode_sites}"
    )

    middleware_tree = _tree(SOURCE_ROOT / "tooling" / "middleware.py")
    assert not _contains_attr_call(middleware_tree, "set_mode")
    assert _type_annotation_mentions(middleware_tree, "PermissionConfirmationSink")
    assert not _type_annotation_mentions(middleware_tree, "PermissionController")

    # PR4：基础 PermissionMode 只含通用安全语义，不允许 plan/auto 业务概念。
    permission_source = (SOURCE_ROOT / "permission_state.py").read_text(
        encoding="utf-8"
    )
    assert '"plan"' not in permission_source
    assert '"auto"' not in permission_source

    # ToolCapabilities 不得再携带 plan 专用能力位。
    capabilities_source = (SOURCE_ROOT / "tooling" / "types.py").read_text(
        encoding="utf-8"
    )
    assert "allowed_in_plan" not in capabilities_source

    # PermissionPolicy 的通用判定接口不接受 plan 文件路径。
    policy_tree = _tree(SOURCE_ROOT / "tooling" / "permission.py")
    assert not _attribute_references(policy_tree, "plan_file_path")


def test_tooling_does_not_import_product_runtimes() -> None:
    """tooling 包不得 import PlanRuntime / Supervisor（Harness 不认识产品运行时）。"""
    violations: dict[str, tuple[str, ...]] = {}
    for path in _source_files("tooling"):
        imported = _product_import_roots(path, _tree(path))
        bad = sorted(imported & {"capabilities", "supervisor"})
        if bad:
            violations[_source_key(path)] = tuple(bad)
    assert not violations, f"tooling 包反向绑定产品运行时: {violations}"

    context_tree = _tree(SOURCE_ROOT / "tooling" / "context.py")
    context_fields = _class_annotated_fields(context_tree, "ToolContext")
    assert not {"plan", "auto_permission_fn"} & context_fields


def test_plan_state_has_one_owner_and_live_read_port() -> None:
    context_path = SOURCE_ROOT / "tooling" / "context.py"
    context_tree = _tree(context_path)
    context_fields = _class_annotated_fields(context_tree, "ToolContext")
    assert "plan" not in context_fields
    assert "plan_file_path" not in context_fields

    plan_tree = _tree(SOURCE_ROOT / "capabilities" / "plan" / "runtime.py")
    assert _class_annotated_fields(plan_tree, "PlanState") == _PLAN_STATE_FIELDS

    adapter_fields = _self_fields(
        _tree(SOURCE_ROOT / "adapters" / "coding_session_backend.py")
    )
    assert not _REMOVED_AGENT_PLAN_SYMBOLS & adapter_fields
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

    lifecycle_tree = _tree(SOURCE_ROOT / "runtime" / "session.py")
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
    assert state_constructors == {"composition/agent_builder.py": 1}
    assert runtime_constructors == {"composition/agent_builder.py": 1}

    mutations = {
        _source_key(path): sorted(_plan_state_mutations(_tree(path)))
        for path in _source_files()
        if _source_key(path) != "capabilities/plan/runtime.py"
        and _plan_state_mutations(_tree(path))
    }
    assert not mutations, f"PlanState writes must stay in PlanRuntime: {mutations}"

    # PR4：PermissionMiddleware 不得读取 Plan 视图或执行 plan/auto 特判。
    middleware_source = (SOURCE_ROOT / "tooling" / "middleware.py").read_text(
        encoding="utf-8"
    )
    assert "context.plan_file_path" not in middleware_source
    assert "context.plan" not in middleware_source
    assert 'mode == "plan"' not in middleware_source
    assert 'mode != "auto"' not in middleware_source

    # PlanRuntime 不再依赖 PermissionController（PR4）。
    plan_runtime_source = (
        SOURCE_ROOT / "capabilities" / "plan" / "runtime.py"
    ).read_text(encoding="utf-8")
    assert "PermissionController" not in plan_runtime_source
    assert "permission_state" not in plan_runtime_source


def test_prompt_and_capability_lifecycle_boundaries() -> None:
    plan_runtime_source = (
        SOURCE_ROOT / "capabilities" / "plan" / "runtime.py"
    ).read_text(encoding="utf-8")
    for symbol in (
        "self._base_system_prompt",
        "self._system_prompt",
        "refresh_prompt",
        "_build_prompt",
    ):
        assert symbol not in plan_runtime_source

    lifecycle_source = (SOURCE_ROOT / "runtime" / "session.py").read_text(
        encoding="utf-8"
    )
    assert "PlanRuntime" not in lifecycle_source
    assert ".plan" not in lifecycle_source

    adapter_source = (SOURCE_ROOT / "adapters" / "coding_session_backend.py").read_text(
        encoding="utf-8"
    )
    for symbol in (
        "_before_turn_capabilities",
        "_after_turn_capabilities",
        "_close_capabilities",
        "self._base_system_prompt",
        "self._system_prompt",
    ):
        assert symbol not in adapter_source

    prompt_tree = _tree(SOURCE_ROOT / "prompt.py")
    capability_imports = {
        alias.name
        for node in ast.walk(prompt_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and "capabilit" in node.module
        for alias in node.names
    }
    assert capability_imports <= {"PromptLayer"}

    plan_capability_tree = _tree(
        SOURCE_ROOT / "capabilities" / "plan" / "capability.py"
    )
    render_method = next(
        node
        for node in ast.walk(plan_capability_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "render"
    )
    assert not any(
        isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete))
        for node in ast.walk(render_method)
    )
    participant = next(
        node
        for node in plan_capability_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PlanSessionParticipant"
    )
    assert {
        node.name for node in participant.body if isinstance(node, ast.AsyncFunctionDef)
    } == {"on_new_session", "on_restore_session"}


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


def _type_annotation_mentions(tree: ast.Module, name: str) -> bool:
    """Check whether *name* appears in any type annotation in *tree*."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


def test_removed_skill_command_symbols_do_not_return() -> None:
    violations = {
        _source_key(path): sorted(_removed_skill_command_symbols(_tree(path)))
        for path in _source_files()
        if _removed_skill_command_symbols(_tree(path))
    }

    assert not violations, f"旧 /skill: 半成品入口不得重新进入产品代码: {violations}"


def test_removed_external_tool_protocol_stays_deleted() -> None:
    """PR7b 强否定：被删除的外部工具协议不得以文件、import、配置字段、
    capability name 或 ``.json`` 配置加载逻辑的任何形式回归。"""
    token = _REMOVED_PROTOCOL_TOKEN.casefold()
    hits: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if token in relative.casefold() or token in source.casefold():
            hits.append(relative)
    assert not hits, f"已删除的外部工具协议出现残留: {hits}"


def test_removed_environment_field_stays_out_of_composition() -> None:
    """PR7b 强否定：配置/绑定/组合结果不得重新携带外部工具环境字段。"""
    from dataclasses import fields as dataclass_fields

    from lion_code.composition import (
        AgentComposition,
        AgentConfig,
        InteractionBindings,
        ProviderBindings,
        RuntimeBindings,
        SessionBindings,
        ToolBindings,
    )

    field_names = (
        {field.name for field in dataclass_fields(AgentConfig)}
        | {field.name for field in dataclass_fields(RuntimeBindings)}
        | {
            field.name
            for group in (
                ProviderBindings,
                SessionBindings,
                ToolBindings,
                InteractionBindings,
            )
            for field in dataclass_fields(group)
        }
        | {field.name for field in dataclass_fields(AgentComposition)}
    )
    assert not field_names & {"tool_environment"}


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
    old_skill = ast.parse("def parse_skill_invocation():\n    return '/skill:'\n")
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
        "    setattr(plan_state, 'status', 'active')\n"
    )
    plan_path_mirror = ast.parse(
        "def sync(alias):\n    alias.plan_file_path = 'plan.md'\n"
    )
    usage_mutation = ast.parse(
        "def bypass(ledger):\n"
        "    alias = ledger\n"
        "    ledger._input_tokens = 1\n"
        "    alias._turns += 1\n"
        "    write = object.__setattr__\n"
        "    write(alias, '_responses', 2)\n"
        "    remove = delattr\n"
        "    remove(alias, '_last_prompt_tokens')\n"
        "    bound_write = alias.__setattr__\n"
        "    bound_write('_output_tokens', 3)\n"
    )
    constructor_alias = ast.parse(
        "from lion_code.usage import UsageLedger as Ledger\n"
        "Owner = Ledger\n"
        "def build():\n"
        "    return Owner()\n"
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
    assert _removed_skill_command_symbols(old_skill) == frozenset(
        {"/skill:", "parse_skill_invocation"}
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
            "setattr:status",
        }
    )
    assert _attribute_references(plan_path_mirror, "plan_file_path") == frozenset(
        {"plan_file_path"}
    )
    assert _attribute_mutations(
        usage_mutation,
        _USAGE_LEDGER_FIELDS,
    ) == frozenset(
        {
            "_input_tokens",
            "_turns",
            "delattr:_last_prompt_tokens",
            "setattr:_output_tokens",
            "setattr:_responses",
        }
    )
    assert _named_constructor_count(constructor_alias, "UsageLedger") == 1


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


def test_domain_runtimes_use_only_narrow_dependencies() -> None:
    """Domain runtimes must not regain an Agent-shaped host or private runtime seam."""

    scoped = {
        "supervisor.py": ("Supervisor",),
        "capabilities/subagent/factory.py": ("SubagentFactory",),
    }
    removed_hosts = {
        "AutonomyHost",
        "SubagentFactoryHost",
    }
    for filename, class_names in scoped.items():
        tree = _tree(SOURCE_ROOT / filename)
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined.intersection(removed_hosts), filename

        service_locators = {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and (
                node.name in {"RuntimeContext", "AgentServices", "DomainContext"}
                or node.name.endswith("Services")
            )
        }
        assert not service_locators, {filename: service_locators}

        imported: set[str] = set()
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                imported.update(alias.name for alias in item.names)
            elif isinstance(item, ast.ImportFrom):
                if item.level and item.module:
                    imported.add(f"lion_code.{item.module}")
                elif item.module:
                    imported.add(item.module)
        if filename == "supervisor.py":
            assert "lion_code.agent" not in imported
            assert "lion_code.runtime" not in imported

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name not in class_names:
                continue
            init = next(
                (
                    item
                    for item in node.body
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__"
                ),
                None,
            )
            assert init is not None, f"{filename}:{node.name} missing __init__"
            parameters = {
                arg.arg
                for arg in [
                    *init.args.posonlyargs,
                    *init.args.args,
                    *init.args.kwonlyargs,
                ]
            }
            assert not parameters.intersection({"agent", "host"}), {
                filename: sorted(parameters)
            }

        forbidden_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"_core_runtime", "_host"}
        }
        assert not forbidden_attributes, {filename: sorted(forbidden_attributes)}


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
