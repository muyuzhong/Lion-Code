"""PR5 Bare Composition：无高级 Feature 的真实对象图。

验收：
1. CapabilityRegistry() 为空是合法状态。
2. registry names == () 时对象图仍能构造。
3. Bare composition 不创建 Memory/Plan/MCP/SubAgent/Skill/Autonomy/Dream/Learning。
4. 不存在为了构造通过而增加的 Null Feature（缺失即 None，不造假对象）。
5. Tool Runtime 不依赖 McpManager。
6. Meta base prompt 不引用不存在的 Feature。
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from lion_code.composition import (
    PRODUCT_CAPABILITIES,
    AgentConfig,
    AgentDependencies,
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

# Bare 图禁止出现的 Feature 字段（AgentComposition 中应为 None）。
_FEATURE_FIELDS = (
    "mcp_manager",
    "mcp_state",
    "plan",
    "subagent_factory",
    "subagent_executor",
    "skill_runtime",
    "mcp_capability",
    "session_memory_coordinator",
    "autonomy",
    "learning",
    "model_query",
)


def _bare_composition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = AgentConfig(model="claude-opus-4-6", terminal_output=False)
    dependencies = AgentDependencies(tool_registry=ToolRegistry())
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch("lion_code.agent.create_provider", return_value=provider):
        return build_agent_composition(config, dependencies)


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
    """Bare composition 不创建 Memory/Plan/MCP/SubAgent/Skill/Autonomy/Dream/Learning。"""
    composition = _bare_composition(tmp_path, monkeypatch)
    for field in _FEATURE_FIELDS:
        assert getattr(composition, field) is None, field


def test_bare_graph_has_no_mcp_manager(tmp_path, monkeypatch) -> None:
    """Bare 图不创建 McpManager：ToolEnvironment 也不持有一个。"""
    composition = _bare_composition(tmp_path, monkeypatch)
    assert composition.mcp_manager is None
    assert composition.tool_environment.mcp_manager is None


def test_full_product_has_all_features(tmp_path, monkeypatch) -> None:
    """PRODUCT_CAPABILITIES 显式选择后，Full Product 恢复全部 Feature。"""
    monkeypatch.chdir(tmp_path)
    config = AgentConfig(model="claude-opus-4-6", terminal_output=False)
    dependencies = AgentDependencies(tool_registry=ToolRegistry())
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch("lion_code.agent.create_provider", return_value=provider):
        composition = build_agent_composition(
            config,
            dependencies,
            capabilities=PRODUCT_CAPABILITIES,
        )
    for field in _FEATURE_FIELDS:
        assert getattr(composition, field) is not None, field


def test_tool_runtime_does_not_import_mcp() -> None:
    """Tool Runtime 不依赖 McpManager（无 import、无构造参数）。"""
    source = (SOURCE_ROOT / "tooling" / "runtime.py").read_text(encoding="utf-8")
    assert "mcp" not in source.casefold()
    tree = ast.parse(source, filename="runtime.py")
    init = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    args = [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs]
    assert not any("mcp" in arg.arg for arg in args)


def test_base_prompt_does_not_reference_features() -> None:
    """Meta base prompt 不引用不存在的 Feature。"""
    static = build_static_system_prompt()
    dynamic = build_dynamic_system_context(deferred_tool_names=[])
    combined = static + dynamic

    # 使用 agent tool / memory / skills / MCP / Plan 的显式指引词。
    for marker in (
        "Use the `agent` tool",
        "Auto Memory",
        "Available Skills",
        "mcp__",
        "MCP tools",
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
