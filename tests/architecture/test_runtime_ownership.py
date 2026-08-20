"""PR3 Runtime Ownership 的 object graph / dependency 架构约束。

证明 Runtime object graph 可拓扑排序：
- AgentRuntime 与 ProviderController 互不持有（双向禁止）；
- Deferred* 二段式绑定不复存在；
- 三个 Runtime Owner 各自的 mutable state 唯一；
- runtime 包不反向依赖 Application/TUI 等上层。
"""

from __future__ import annotations

import ast
import functools
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from lion_code.composition import (
    AgentConfig,
    CodingProfile,
    FullProfile,
    MinimalProfile,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
    ToolBindings,
    build_agent_composition,
)
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

RUNTIME_DIR = SOURCE_ROOT / "runtime"
REMOVED_DEFERRED_SYMBOLS = frozenset(
    {
        "DeferredProviderRuntimePort",
        "DeferredModelContextControl",
        "DeferredBackgroundScheduler",
        "SessionRecorderConfigurationRecorder",
    }
)
REMOVED_RUNTIME_CLASSES = frozenset(
    {
        "AgentRuntimeCoordinator",
        "LionAgentRuntime",
        "SessionLifecycle",
        "ProviderManager",
    }
)
# ContextRuntime 唯一拥有的 compaction / 限制缓存 mutable state。
_CONTEXT_STATE_FIELDS = frozenset(
    {
        "_compaction_required",
        "_compaction_task",
        "_resolved_model_limits_for",
        "effective_window",
    }
)
# ConversationRuntime 唯一拥有的 live provider / harness 状态。
_CONVERSATION_STATE_FIELDS = frozenset({"_provider", "harness"})
HARNESS_MUTATION_METHODS = frozenset({"clear_queues", "replace_messages"})


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _source_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _source_key(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _init_arguments(class_node: ast.ClassDef) -> set[str]:
    init = next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    return {
        argument.arg
        for argument in [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs]
    }


def _self_fields(tree: ast.Module) -> set[str]:
    fields: set[str] = set()
    for node in ast.walk(tree):
        targets: tuple[ast.expr, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                fields.add(target.attr)
    return fields


def _referenced_symbols(tree: ast.Module, names: frozenset[str]) -> frozenset[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in names:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            found.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in names:
                found.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names if alias.name in names)
    return frozenset(found)


def _import_roots(tree: ast.Module) -> frozenset[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            # 相对 import：从模块路径解析（runtime 内只可能指向 lion_code 子包）。
            roots.add((node.module or "").split(".")[0])
    return frozenset(roots)


def _bare_composition():
    config = AgentConfig(model="claude-opus-4-6", terminal_output=False)
    bindings = RuntimeBindings(tool=ToolBindings(tool_registry=ToolRegistry()))
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=provider,
    ):
        return build_agent_composition(
            MinimalProfile(), config=config, bindings=bindings
        )


def _profile_composition(profile, tmp_path: Path):
    provider = Mock()
    provider.aclose = AsyncMock()
    bindings = RuntimeBindings(
        provider=ProviderBindings(provider=provider),
        session=SessionBindings(
            session_repository=SessionRepository(
                tmp_path / type(profile).__name__.casefold()
            )
        ),
    )
    return build_agent_composition(
        profile,
        config=AgentConfig(api_key="test-key", terminal_output=False),
        bindings=bindings,
    )


def _slot_names(value: object) -> tuple[str, ...]:
    names: list[str] = []
    for cls in type(value).__mro__:
        slots = cls.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        names.extend(slot for slot in slots if slot not in {"__dict__", "__weakref__"})
    return tuple(dict.fromkeys(names))


def _reachable_paths(root: object) -> dict[int, str]:
    """只沿 Lion composition 对象展开引用，不执行 callable 或读取 globals。"""

    primitive_types = (str, bytes, bytearray, int, float, complex, bool)
    visited: set[int] = set()
    paths: dict[int, str] = {}

    def visit(value: object, path: str) -> None:
        if value is None or isinstance(value, primitive_types):
            return
        if isinstance(value, types.ModuleType | type):
            return
        if isinstance(value, dict):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            paths[identity] = path
            for index, (key, child) in enumerate(value.items()):
                visit(key, f"{path}.key[{index}]")
                visit(child, f"{path}[{key!r}]")
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            paths[identity] = path
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if isinstance(value, functools.partial):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            paths[identity] = path
            visit(value.func, f"{path}.func")
            for index, child in enumerate(value.args):
                visit(child, f"{path}.args[{index}]")
            for key, child in (value.keywords or {}).items():
                visit(child, f"{path}.keywords[{key!r}]")
            return
        if isinstance(value, types.MethodType):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            paths[identity] = path
            visit(value.__self__, f"{path}.__self__")
            visit(value.__func__, f"{path}.__func__")
            return
        if isinstance(value, types.FunctionType):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            paths[identity] = path
            if value.__closure__ is not None:
                for index, cell in enumerate(value.__closure__):
                    try:
                        contents = cell.cell_contents
                    except ValueError:
                        continue
                    visit(contents, f"{path}.__closure__[{index}]")
            return

        module_name = getattr(type(value), "__module__", "")
        if not module_name.startswith("lion_code"):
            return
        identity = id(value)
        if identity in visited:
            return
        visited.add(identity)
        paths[identity] = path
        if hasattr(value, "__dict__"):
            for name, child in vars(value).items():
                visit(child, f"{path}.{name}")
        for slot in _slot_names(value):
            try:
                child = getattr(value, slot)
            except AttributeError:
                continue
            visit(child, f"{path}.{slot}")

    visit(root, "$root")
    return paths


def _assert_not_reachable(root: object, target: object, *, label: str) -> None:
    paths = _reachable_paths(root)
    assert id(target) not in paths, (
        f"{label} 仍可经 {paths.get(id(target))} 到达 ProviderController"
    )


def test_builder_has_no_provider_controller_closure() -> None:
    tree = _tree(SOURCE_ROOT / "composition" / "agent_builder.py")
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_agent_composition"
    )
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if node is builder:
            continue
        if any(
            isinstance(name, ast.Name)
            and isinstance(name.ctx, ast.Load)
            and name.id == "provider_controller"
            for name in ast.walk(node)
        ):
            violations.append(getattr(node, "name", "<lambda>"))
    assert not violations, (
        f"builder closure 不得捕获未来 provider_controller: {violations}"
    )


def test_reachable_runtime_graph_has_no_provider_controller(tmp_path) -> None:
    profiles = (MinimalProfile(), CodingProfile(), FullProfile())
    for profile in profiles:
        composition = _profile_composition(profile, tmp_path)
        controller = composition.runtime.provider_controller
        profile_name = type(profile).__name__
        _assert_not_reachable(
            composition.runtime.agent,
            controller,
            label=f"{profile_name}.AgentRuntime",
        )
        _assert_not_reachable(
            composition.runtime.session,
            controller,
            label=f"{profile_name}.SessionRuntime",
        )
        _assert_not_reachable(
            composition.capabilities.runtime,
            controller,
            label=f"{profile_name}.CapabilityRuntime",
        )
        if composition.capabilities.subagent_factory is not None:
            _assert_not_reachable(
                composition.capabilities.subagent_factory,
                controller,
                label=f"{profile_name}.SubagentFactory",
            )


# ---------------------------------------------------------------------------
# 1/2. AgentRuntime 与 ProviderController 互不持有
# ---------------------------------------------------------------------------


def test_agent_runtime_does_not_hold_provider_controller() -> None:
    agent_tree = _tree(RUNTIME_DIR / "agent.py")
    assert not _referenced_symbols(
        agent_tree, frozenset({"ProviderController", "provider_controller"})
    ), "AgentRuntime 不得引用 ProviderController"

    builder_tree = _tree(SOURCE_ROOT / "composition" / "agent_builder.py")
    agent_runtime_init = next(
        node
        for node in ast.walk(builder_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AgentRuntime"
    )
    wired = {
        keyword.arg
        for keyword in agent_runtime_init.keywords
        if keyword.arg is not None
    }
    assert not wired & {
        "provider_controller",
        "provider_manager",
    }, f"Composition Root 不得把 ProviderController 注入 AgentRuntime: {wired}"


def test_provider_controller_does_not_hold_agent_runtime() -> None:
    provider_tree = _tree(RUNTIME_DIR / "provider.py")
    assert not _referenced_symbols(
        provider_tree, frozenset({"AgentRuntime", "agent_runtime"})
    ), "ProviderController 不得引用 AgentRuntime"

    controller = _class(provider_tree, "ProviderController")
    arguments = _init_arguments(controller)
    assert not arguments & {"agent", "agent_runtime", "coordinator"}
    assert arguments >= {"conversation", "context", "recorder"}, (
        "ProviderController 必须经三个 Runtime 窄端口对外作用"
    )

    builder_tree = _tree(SOURCE_ROOT / "composition" / "agent_builder.py")
    controller_init = next(
        node
        for node in ast.walk(builder_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ProviderController"
    )
    wired = {
        keyword.arg for keyword in controller_init.keywords if keyword.arg is not None
    }
    assert not wired & {"agent", "agent_runtime", "coordinator"}


def test_runtime_graph_has_no_bidirectional_references() -> None:
    """行为断言：对象图里 AgentRuntime 与 ProviderController 互不直接持有。"""

    composition = _bare_composition()
    graph = composition.runtime
    controller = graph.provider_controller
    agent_runtime = graph.agent

    for value in vars(agent_runtime).values():
        assert value is not controller
        if isinstance(value, (list, tuple, set)):
            assert controller not in value
    for value in vars(controller).values():
        assert value is not agent_runtime
        if isinstance(value, (list, tuple, set)):
            assert agent_runtime not in value


# ---------------------------------------------------------------------------
# 3/4/5. Deferred* 二段式绑定不复存在
# ---------------------------------------------------------------------------


def test_deferred_wiring_symbols_do_not_exist() -> None:
    violations: dict[str, list[str]] = {}
    for path in _source_files():
        found = sorted(_referenced_symbols(_tree(path), REMOVED_DEFERRED_SYMBOLS))
        if found:
            violations[_source_key(path)] = found
    assert not violations, f"Deferred binding 禁止回归: {violations}"

    deferred_bind_methods: dict[str, list[str]] = {}
    for path in _source_files():
        tree = _tree(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "bind"
            ):
                deferred_bind_methods.setdefault(_source_key(path), []).append(
                    f"{_class_of(tree, node)}.{node.name}"
                )
    assert not deferred_bind_methods, (
        f"runtime object graph 不得依赖构造后 bind 的二段式接线: {deferred_bind_methods}"
    )


def _class_of(tree: ast.Module, method: ast.AST) -> str:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if member is method:
                return node.name
    return "<module>"


def test_removed_runtime_class_names_do_not_return() -> None:
    violations: dict[str, list[str]] = {}
    for path in _source_files():
        found = sorted(_referenced_symbols(_tree(path), REMOVED_RUNTIME_CLASSES))
        if found:
            violations[_source_key(path)] = found
    assert not violations, f"旧 Runtime 类名禁止回归: {violations}"


# ---------------------------------------------------------------------------
# 6. SessionRuntime 不访问 AgentRuntime（私有字段或任何引用）
# ---------------------------------------------------------------------------


def test_session_runtime_does_not_access_agent_runtime() -> None:
    session_tree = _tree(RUNTIME_DIR / "session.py")
    assert not _referenced_symbols(
        session_tree, frozenset({"AgentRuntime", "agent_runtime"})
    ), "SessionRuntime 不得引用 AgentRuntime"

    # 私有字段纪律：session.py 不得对其它对象做 `._xxx` 私有属性访问。
    private_access: set[str] = set()
    for node in ast.walk(session_tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and isinstance(node.value, ast.Name)
            and node.value.id != "self"
        ):
            private_access.add(node.attr)
    assert not private_access, f"SessionRuntime 访问了外部私有字段: {private_access}"


# ---------------------------------------------------------------------------
# 7. ContextRuntime 是 context compaction mutable state 的唯一 owner
# ---------------------------------------------------------------------------


def test_context_runtime_owns_compaction_state_exclusively() -> None:
    violations: dict[str, list[str]] = {}
    for path in _source_files():
        key = _source_key(path)
        if key == "runtime/context.py":
            continue
        tree = _tree(path)
        fields = _self_fields(tree) & _CONTEXT_STATE_FIELDS
        if fields:
            violations[key] = sorted(fields)
    assert not violations, (
        f"compaction/限制缓存 mutable state 只允许 ContextRuntime 拥有: {violations}"
    )

    context_tree = _tree(RUNTIME_DIR / "context.py")
    context_fields = _self_fields(context_tree)
    assert _CONTEXT_STATE_FIELDS <= context_fields
    # 决策入口与失效命令都存在于唯一 owner 上。
    methods = {
        node.name
        for node in ast.walk(context_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "prepare_context",
        "should_compact_now",
        "summarize",
        "invalidate_model_limit_cache",
        "replace_context_compactor",
        "on_compacted",
    } <= methods


# ---------------------------------------------------------------------------
# 8. ConversationRuntime 是 active Provider/messages/Harness 的唯一 owner
# ---------------------------------------------------------------------------


def test_conversation_runtime_owns_harness_and_live_provider_exclusively() -> None:
    harness_constructors: dict[str, int] = {}
    harness_mutations: dict[str, set[str]] = {}
    for path in _source_files():
        key = _source_key(path)
        tree = _tree(path)
        count = sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "AgentHarness"
            for node in ast.walk(tree)
        )
        if count:
            harness_constructors[key] = count
        mutations = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in HARNESS_MUTATION_METHODS
        }
        if mutations:
            harness_mutations[key] = mutations
    assert harness_constructors == {"runtime/conversation.py": 1}
    assert harness_mutations == {"runtime/conversation.py": HARNESS_MUTATION_METHODS}, (
        f"Harness 变更入口只允许 ConversationRuntime: {harness_mutations}"
    )

    violations: dict[str, list[str]] = {}
    for path in sorted(RUNTIME_DIR.glob("*.py")):
        if path.name == "conversation.py":
            continue
        fields = _self_fields(_tree(path)) & _CONVERSATION_STATE_FIELDS
        if fields:
            violations[path.name] = sorted(fields)
    assert not violations, (
        f"live provider / harness 字段只允许 ConversationRuntime 拥有: {violations}"
    )

    conversation = _class(_tree(RUNTIME_DIR / "conversation.py"), "ConversationRuntime")
    methods = {
        node.name
        for node in conversation.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"replace_provider", "set_model", "retire_provider", "messages"} <= methods


# ---------------------------------------------------------------------------
# 9. SessionRuntime 是 session lifecycle/recorder 的唯一 owner
# ---------------------------------------------------------------------------


def test_session_runtime_owns_session_lifecycle_exclusively() -> None:
    recorder_constructors: dict[str, int] = {}
    identity_resets: dict[str, int] = {}
    for path in _source_files():
        key = _source_key(path)
        tree = _tree(path)
        count = sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SessionRecorder"
            for node in ast.walk(tree)
        )
        if count:
            recorder_constructors[key] = count
        resets = sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reset"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr in {"_session_state", "session_state"}
            for node in ast.walk(tree)
        )
        if resets:
            identity_resets[key] = resets

    assert recorder_constructors == {
        "adapters/coding_session_backend.py": 1,  # 旧 JSON 迁移的只读站点
        "runtime/session.py": 1,
    }
    assert identity_resets == {"runtime/session.py": 2}

    session = _class(_tree(RUNTIME_DIR / "session.py"), "SessionRuntime")
    methods = {
        node.name
        for node in session.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "new_session",
        "load",
        "restore",
        "ensure_ready",
        "close",
        "record_configuration_change",
    } <= methods


# ---------------------------------------------------------------------------
# 10. Runtime 包没有 Application/TUI 反向依赖
# ---------------------------------------------------------------------------


def test_runtime_package_does_not_import_upper_layers() -> None:
    forbidden = frozenset(
        {"application", "tui", "composition", "meta_agent", "agent", "supervisor"}
    )
    violations: dict[str, set[str]] = {}
    for path in sorted(RUNTIME_DIR.glob("*.py")):
        found = _import_roots(_tree(path)) & forbidden
        if found:
            violations[path.name] = found
    assert not violations, f"runtime 包反向依赖上层: {violations}"


# ---------------------------------------------------------------------------
# Composition 结构：分层组合结果
# ---------------------------------------------------------------------------


def test_agent_composition_is_layered_not_flat() -> None:
    from dataclasses import fields

    from lion_code.composition.agent_builder import (
        AgentComposition,
        CapabilityComposition,
        InteractionComposition,
        RuntimeComposition,
        ToolingComposition,
    )

    composition_fields = {field.name for field in fields(AgentComposition)}
    assert composition_fields == {"runtime", "capabilities", "tooling", "interaction"}
    runtime_fields = {field.name for field in fields(RuntimeComposition)}
    assert runtime_fields == {
        "agent",
        "conversation",
        "session",
        "context",
        "provider_controller",
        "usage",
        "budget",
    }
    capability_fields = {field.name for field in fields(CapabilityComposition)}
    assert capability_fields == {
        "registry",
        "runtime",
        "plan",
        "subagent_factory",
        "subagent_executor",
        "skill_runtime",
    }
    tooling_fields = {field.name for field in fields(ToolingComposition)}
    assert tooling_fields == {
        "registry",
        "runtime",
        "context",
        "permission_policy",
        "prompt_composer",
    }
    interaction_fields = {field.name for field in fields(InteractionComposition)}
    assert interaction_fields == {"notices", "confirmation", "status_sink"}
