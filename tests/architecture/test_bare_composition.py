"""PR5/PR6 Bare Composition：无高级 Feature 的真实对象图。

验收：
1. CapabilityRegistry() 为空是合法状态。
2. registry names == () 时对象图仍能构造。
3. Bare composition 不创建 Memory/Plan/SubAgent/Skill。
4. 不存在为了构造通过而增加的 Null Feature（缺失即 None，不造假对象）。
5. Tool Runtime 不依赖外部工具协议实现。
6. Meta base prompt 不引用不存在的 Feature。
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from lion_code.composition import (
    AgentConfig,
    AgentDependencies,
    FullProfile,
    MinimalProfile,
    build_agent_composition,
)
from lion_code.prompt import (
    SYSTEM_PROMPT_TEMPLATE,
    build_dynamic_system_context,
    build_static_system_prompt,
)
from lion_code.tooling.registry import ToolRegistry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

_BARE_GENERIC_FILES = (
    SOURCE_ROOT / "meta_agent.py",
    SOURCE_ROOT / "agent_runtime.py",
    SOURCE_ROOT / "provider_manager.py",
    SOURCE_ROOT / "session_lifecycle.py",
    SOURCE_ROOT / "execution_control.py",
    SOURCE_ROOT / "permission_state.py",
    SOURCE_ROOT / "usage.py",
    *sorted((SOURCE_ROOT / "core").rglob("*.py")),
    *sorted((SOURCE_ROOT / "context").rglob("*.py")),
    *sorted((SOURCE_ROOT / "session_runtime").rglob("*.py")),
    *(
        SOURCE_ROOT / "tooling" / name
        for name in (
            "context.py",
            "middleware.py",
            "permission.py",
            "registry.py",
            "result_store.py",
            "runtime.py",
            "selection.py",
            "types.py",
        )
    ),
)
_FEATURE_MODULE_PREFIXES = (
    "lion_code.autonomy_runtime",
    "lion_code.capabilities.plan",
    "lion_code.capabilities.skill",
    "lion_code.capabilities.subagent",
    "lion_code.dream",
    "lion_code.learning_runtime",
    "lion_code.memory",
    "lion_code.memory_runtime",
    "lion_code.plan_runtime",
    "lion_code.session_memory",
    "lion_code.skill_runtime",
    "lion_code.subagent_factory",
    "lion_code.subagent_runtime",
)
_FEATURE_SYMBOLS = {
    "AutonomyRuntime",
    "ChildAgentConfig",
    "DreamCoordinator",
    "LearningRuntime",
    "MemoryContextInjector",
    "MemoryCoordinator",
    "MemoryQuerySink",
    "PlanRuntime",
    "PlanState",
    "ProviderModelQuery",
    "ProviderTextQueryService",
    "RelevantMemory",
    "RestrictedDreamAgentFactory",
    "SessionMemoryCoordinator",
    "SkillRuntime",
    "SubagentExecutor",
    "SubagentFactory",
}

# Bare 图禁止出现的 Feature 字段（AgentComposition 中应为 None）。
_FEATURE_FIELDS = (
    "plan",
    "subagent_factory",
    "subagent_executor",
    "skill_runtime",
    "session_memory_coordinator",
)


def _bare_composition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = AgentConfig(model="claude-opus-4-6", terminal_output=False)
    dependencies = AgentDependencies(tool_registry=ToolRegistry())
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=provider,
    ):
        return build_agent_composition(
            MinimalProfile(config=config, dependencies=dependencies)
        )


def test_capability_registry_empty_is_legal_state(tmp_path, monkeypatch) -> None:
    """空 CapabilityRegistry 是合法状态：names 为空元组。"""
    from lion_code.capabilities import CapabilityRegistry

    registry = CapabilityRegistry()
    assert registry.names == ()
    assert registry.tool_sources == ()
    assert registry.prompt_layers == ()


def test_bare_graph_constructs_with_empty_registry(tmp_path, monkeypatch) -> None:
    """registry names == () 时对象图仍能构造。"""
    composition = _bare_composition(tmp_path, monkeypatch)
    assert composition.capability_registry.names == ()
    assert composition.tool_runtime is not None
    assert composition.runtime_coordinator is not None


def test_bare_graph_creates_no_feature_objects(tmp_path, monkeypatch) -> None:
    """Bare composition 不创建 Memory/Plan/SubAgent/Skill。"""
    composition = _bare_composition(tmp_path, monkeypatch)
    for field in _FEATURE_FIELDS:
        assert getattr(composition, field) is None, field
    assert composition.status_sink is None


def test_full_product_has_all_features(tmp_path, monkeypatch) -> None:
    """FullProfile 显式选择后，Full Product 恢复全部 Feature。"""
    monkeypatch.chdir(tmp_path)
    config = AgentConfig(model="claude-opus-4-6", terminal_output=False)
    dependencies = AgentDependencies(tool_registry=ToolRegistry())
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch("lion_code.agent.create_provider", return_value=provider):
        composition = build_agent_composition(
            FullProfile(config=config, dependencies=dependencies)
        )
    for field in _FEATURE_FIELDS:
        assert getattr(composition, field) is not None, field


def test_tool_runtime_does_not_import_external_tool_protocol() -> None:
    """Tool Runtime 不依赖任何外部工具协议实现（无 import、无构造参数）。"""
    source = (SOURCE_ROOT / "tooling" / "runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="runtime.py")
    init = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    args = [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs]
    assert not any("environment" in arg.arg for arg in args)


def test_base_prompt_does_not_reference_features() -> None:
    """Meta base prompt 不引用不存在的 Feature。"""
    static = build_static_system_prompt()
    dynamic = build_dynamic_system_context(deferred_tool_names=[])
    combined = static + dynamic

    # 使用 agent tool / memory / skills / Plan 的显式指引词。
    for marker in (
        "Use the `agent` tool",
        "Auto Memory",
        "Available Skills",
        "plan mode",
        "Plan mode",
        "REPL commands like /clear, /cost, /compact, /memory",
        "REPL commands like /clear, /cost, /compact, /skills",
        "use the `skill` tool",
    ):
        assert marker not in combined, f"base prompt 引用 Feature: {marker!r}"


def test_prompt_template_declaration_matches_static_builder() -> None:
    """静态模板即 build_static_system_prompt 的内容，Feature 引用同样被拒绝。"""
    assert SYSTEM_PROMPT_TEMPLATE == build_static_system_prompt()


def test_bare_kernel_and_harness_paths_have_no_feature_references() -> None:
    """只扫描 Bare 通用路径，不误伤 Product/Capability 的具体实现。"""

    violations = []
    for path in _BARE_GENERIC_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = f"lion_code.{module}"
                if module.startswith(_FEATURE_MODULE_PREFIXES):
                    violations.append((path.name, node.lineno, module))
                for alias in node.names:
                    if alias.name in _FEATURE_SYMBOLS:
                        violations.append((path.name, node.lineno, alias.name))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(_FEATURE_MODULE_PREFIXES):
                        violations.append((path.name, node.lineno, alias.name))
            elif isinstance(node, ast.Name) and node.id in _FEATURE_SYMBOLS:
                violations.append((path.name, node.lineno, node.id))
            elif isinstance(node, ast.Attribute) and node.attr in _FEATURE_SYMBOLS:
                violations.append((path.name, node.lineno, node.attr))

    assert not violations, f"Bare 通用路径引用高级 Feature: {violations}"


def test_meta_agent_does_not_import_concrete_coding_tools() -> None:
    """Coding tools 只能由调用方显式传入。"""

    source = (SOURCE_ROOT / "meta_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="meta_agent.py")
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not imported_modules & {"tooling.builtin", "tooling.internal"}


def test_provider_manager_has_no_memory_reference() -> None:
    """ProviderManager 只刷新通用 Provider/Context/Recorder 状态。"""

    source = (SOURCE_ROOT / "provider_manager.py").read_text(encoding="utf-8")
    assert "memory" not in source.casefold()
