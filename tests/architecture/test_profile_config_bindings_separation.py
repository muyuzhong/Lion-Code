"""PR2 Profile / AgentConfig / RuntimeBindings 三轴分离的结构门禁。

验收：
1. Profile dataclass 不出现 config / bindings / dependencies 字段。
2. Profile 源码不引用 SessionRepository / Provider / ContextManager 等
   concrete runtime dependencies。
3. AgentConfig 不保存 mutable runtime object（字段注解只允许值类型）。
4. RuntimeBindings 及其分组是 frozen wiring value，不是 runtime state owner：
   AgentComposition 不保留 bindings/config 引用。
5. extension_specs 字段覆盖 Minimal/Coding/Full（#62 正交化不被撤销）。
6. Composition Root 是三轴唯一汇合点：profile + config + bindings 同时出现在
   参数里的函数只有 build_agent_composition / build_profile_agent；
   三轴符号不得出现在 Kernel/Harness/Capability 等其余模块。
"""

from __future__ import annotations

import ast
from dataclasses import MISSING, fields
from pathlib import Path

from lion_code.composition import (
    AgentComposition,
    AgentConfig,
    CodingProfile,
    FullProfile,
    InteractionBindings,
    MinimalProfile,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
    ToolBindings,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
PROFILES_PATH = SOURCE_ROOT / "composition" / "profiles.py"
CONFIG_PATH = SOURCE_ROOT / "composition" / "config.py"
BINDINGS_PATH = SOURCE_ROOT / "composition" / "bindings.py"

_PROFILE_CLASSES = (MinimalProfile, CodingProfile, FullProfile)
_BINDING_GROUPS = (
    ProviderBindings,
    SessionBindings,
    ToolBindings,
    InteractionBindings,
)

# concrete runtime dependency 符号：Profile 不允许以任何形式引用。
_RUNTIME_DEPENDENCY_SYMBOLS = {
    "SessionRepository",
    "SessionRecorder",
    "ModelProvider",
    "ProviderManager",
    "ProviderFactory",
    "ContextManager",
    "ContextCompactor",
    "ModelLimitsResolver",
    "ToolRegistry",
    "ToolRuntime",
    "CommandExecutionBackend",
    "LocalCommandExecutionBackend",
    "PermissionController",
    "UsageLedger",
    "BudgetPolicy",
    "TerminalRenderer",
}

# 三轴符号：只允许出现在 Composition Root、构造入口与包根导出。
_AXIS_SYMBOLS = {
    "MinimalProfile",
    "CodingProfile",
    "FullProfile",
    "Profile",
    "AgentConfig",
    "RuntimeBindings",
    "ProviderBindings",
    "SessionBindings",
    "ToolBindings",
    "InteractionBindings",
}
_AXIS_ALLOWED_FILES = {
    "composition/__init__.py",
    "composition/agent_builder.py",
    "composition/profiles.py",
    "composition/config.py",
    "composition/bindings.py",
    "meta_agent.py",
    "agent.py",
    "__init__.py",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dataclass_field_annotations(path: Path, class_name: str) -> dict[str, str]:
    tree = _tree(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                member.target.id: ast.unparse(member.annotation)
                for member in node.body
                if isinstance(member, ast.AnnAssign)
                and isinstance(member.target, ast.Name)
            }
    raise AssertionError(f"missing class {class_name} in {path}")


def test_profiles_do_not_carry_config_bindings_or_dependency_fields() -> None:
    forbidden = {
        "config",
        "bindings",
        "dependencies",
        "provider",
        "provider_factory",
        "session_repository",
        "context_manager",
        "context_compactor",
        "model_limits_resolver",
        "tool_registry",
        "command_backend",
        "confirm_fn",
        "terminal_renderer_factory",
    }
    for profile_type in _PROFILE_CLASSES:
        field_names = {field.name for field in fields(profile_type)}
        assert not field_names & forbidden, (
            f"{profile_type.__name__} 携带非组合字段: {sorted(field_names & forbidden)}"
        )


def test_profiles_do_not_reference_concrete_runtime_dependencies() -> None:
    tree = _tree(PROFILES_PATH)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _RUNTIME_DEPENDENCY_SYMBOLS:
            raise AssertionError(f"profiles.py 引用 concrete dependency: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in (
            _RUNTIME_DEPENDENCY_SYMBOLS
        ):
            raise AssertionError(f"profiles.py 引用 concrete dependency: {node.attr}")
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "session_runtime" not in node.module
            assert "core.provider" not in node.module
            assert "tooling.execution" not in node.module
    # Profile 模块不 import config/bindings：WHAT 不知道另外两轴的存在。
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            assert node.module not in {"config", "bindings"}, (
                f"profiles.py import 了 {node.module}"
            )


def test_agent_config_holds_only_value_types() -> None:
    """AgentConfig 字段注解不得包含任何 runtime object 类型。"""
    for class_name in ("AgentConfig",):
        annotations = _dataclass_field_annotations(CONFIG_PATH, class_name)
        for field_name, annotation in annotations.items():
            for symbol in _RUNTIME_DEPENDENCY_SYMBOLS:
                assert symbol not in annotation, (
                    f"AgentConfig.{field_name} 引用 runtime object: {symbol}"
                )
            assert "Callable" not in annotation, (
                f"AgentConfig.{field_name} 携带回调/工厂: {annotation}"
            )
    # 默认值全部是值类型，不含可变运行时对象。
    for field_info in fields(AgentConfig):
        default = field_info.default
        if default is MISSING or default is None:
            continue
        assert isinstance(default, (str, bool, int, float)), (
            f"AgentConfig.{field_info.name} 默认值不是值类型: {default!r}"
        )


def test_runtime_bindings_are_frozen_wiring_not_state() -> None:
    """RuntimeBindings 及四组 binding 是 frozen value；组合结果不保留三轴引用。"""
    for binding_type in (RuntimeBindings, *_BINDING_GROUPS):
        field_names = {field.name for field in fields(binding_type)}
        assert field_names, binding_type.__name__

    # RuntimeBindings 只由四组 binding 组成，不接受平铺依赖字段。
    top_fields = {field.name for field in fields(RuntimeBindings)}
    assert top_fields == {"provider", "session", "tool", "interaction"}

    # binding dataclass 不定义运行时方法（不是 service / state owner）。
    tree = _tree(BINDINGS_PATH)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert member.name == "__post_init__", (
                    f"{node.name} 定义了运行时方法: {member.name}"
                )

    # AgentComposition 是 runtime graph，不回持三轴输入。
    composition_fields = {field.name for field in fields(AgentComposition)}
    assert not composition_fields & {
        "profile",
        "config",
        "bindings",
        "dependencies",
    }


def test_extension_specs_cover_all_profiles() -> None:
    """extension_specs 字段在三种 Profile 上保持正交入口（#62 行为不回退）。"""
    for profile_type in _PROFILE_CLASSES:
        field_names = {field.name for field in fields(profile_type)}
        assert "extension_specs" in field_names, profile_type.__name__


def test_composition_root_is_only_axis_confluence_point() -> None:
    """profile 与 config/bindings 同时出现在参数里的函数只有两个构造入口。"""
    allowed_signatures = {
        ("agent_builder.py", "build_agent_composition"),
        ("meta_agent.py", "build_profile_agent"),
    }
    violations = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(SOURCE_ROOT)
        tree = _tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {
                argument.arg
                for argument in [
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ]
            }
            if "profile" in params and params & {"config", "bindings"}:
                signature = (relative.parts[-1], node.name)
                if signature not in allowed_signatures:
                    violations.append((*signature, relative.as_posix()))
    assert not violations, f"三轴在非 Composition Root 汇合: {violations}"


def test_axis_symbols_do_not_leak_outside_composition_surface() -> None:
    """三轴符号不得出现在 Kernel/Harness/Capability 等其余模块。"""
    violations = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(SOURCE_ROOT)
        if relative.as_posix() in _AXIS_ALLOWED_FILES:
            continue
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _AXIS_SYMBOLS:
                violations.append((relative.as_posix(), node.lineno, node.id))
            elif isinstance(node, ast.Attribute) and node.attr in _AXIS_SYMBOLS:
                violations.append((relative.as_posix(), node.lineno, node.attr))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _AXIS_SYMBOLS:
                        violations.append(
                            (relative.as_posix(), node.lineno, alias.name)
                        )
    assert not violations, f"三轴符号泄漏出 Composition 表面: {violations}"
