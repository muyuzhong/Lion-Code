"""Composition Root 与 Capability 扩展面的架构验收。"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from lion_code.capabilities.types import CapabilitySpec
from lion_code.composition import (
    AgentComposition,
    AgentConfig,
    FullProfile,
    MinimalProfile,
    RuntimeBindings,
    ToolBindings,
    build_agent_composition,
)
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
BUILDER_PATH = SOURCE_ROOT / "composition" / "agent_builder.py"


class ExampleToolSource:
    def tools(self) -> tuple[LionTool, ...]:
        return ()


class ExamplePromptLayer:
    layer_id = "example"

    def render(self) -> str:
        return "example capability prompt"


class ExampleSessionParticipant:
    def __init__(self) -> None:
        self.new_sessions = 0

    async def on_new_session(self) -> None:
        self.new_sessions += 1

    async def on_restore_session(self) -> None:
        return None


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _method(
    tree: ast.Module,
    class_name: str,
    method_name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for member in node.body:
            if (
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name == method_name
            ):
                return member
    raise AssertionError(f"missing {class_name}.{method_name}")


def test_config_bindings_and_profiles_are_separate_frozen_values() -> None:
    config = AgentConfig()
    bindings = RuntimeBindings()
    profile = MinimalProfile()

    with pytest.raises(FrozenInstanceError):
        setattr(config, "model", "mutated")
    with pytest.raises(FrozenInstanceError):
        setattr(bindings.tool, "tool_registry", None)
    with pytest.raises(FrozenInstanceError):
        setattr(profile, "system_prompt", "mutated")

    config_fields = {field.name for field in fields(config)}
    binding_fields = {field.name for field in fields(bindings)}
    profile_fields = {field.name for field in fields(profile)}
    assert "tool_registry" not in config_fields
    assert "context_manager" not in config_fields
    assert "custom_system_prompt" not in config_fields
    assert "custom_tools" not in config_fields
    assert "extra_capabilities" not in binding_fields
    assert "model" not in binding_fields
    assert "permission_mode" not in binding_fields
    assert "config" not in profile_fields
    assert "bindings" not in profile_fields
    assert "dependencies" not in profile_fields
    assert "capabilities" not in profile_fields


@pytest.mark.asyncio
async def test_example_capability_needs_only_spec_registration_and_tests(
    tmp_path, monkeypatch
):
    """新 Capability 不需要修改 Agent、Runtime、Application 或 TUI。"""

    monkeypatch.chdir(tmp_path)
    participant = ExampleSessionParticipant()
    spec = CapabilitySpec(
        name="example",
        tool_sources=(ExampleToolSource(),),
        prompt_layers=(ExamplePromptLayer(),),
        session_participants=(participant,),
    )
    config = AgentConfig(
        model="claude-opus-4-6",
        api_key="test-key",
        terminal_output=False,
    )
    bindings = RuntimeBindings(tool=ToolBindings(tool_registry=ToolRegistry()))
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch(
        "lion_code.composition.agent_builder.create_provider", return_value=provider
    ):
        composition = build_agent_composition(
            FullProfile(extension_specs=(spec,)),
            config=config,
            bindings=bindings,
        )

    assert len(composition.capabilities.registry.prompt_layers) == 2
    assert (
        "example capability prompt" in composition.tooling.prompt_composer.get_system()
    )
    await composition.capabilities.runtime.on_new_session()
    assert participant.new_sessions == 1
    await composition.capabilities.runtime.close()


def test_meta_agent_is_a_feature_neutral_facade():
    tree = _tree(SOURCE_ROOT / "meta_agent.py")
    meta_agent = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "MetaAgent"
    )
    methods = {
        node.name
        for node in meta_agent.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not methods & {
        "list_sessions",
        "restore_latest",
        "show_cost",
        "toggle_plan_mode",
        "set_plan_approval_fn",
    }


def test_builder_is_a_construction_function_not_a_service_locator():
    tree = _tree(BUILDER_PATH)
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert not {"AgentBuilder", "AgentContainer", "ServiceLocator"} & class_names
    assert not {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } & {"get", "resolve", "services"}
    assert not any(
        isinstance(node, ast.Name) and node.id == "Agent" for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and "builder" in node.attr.casefold()
        for node in ast.walk(_tree(SOURCE_ROOT / "meta_agent.py"))
    )


_SUPERVISOR_MODULES = ("supervisor",)
_SUPERVISOR_SYMBOLS = (
    "CheckpointStore",
    "Goal",
    "RetryPolicy",
    "Supervisor",
)
_SUPERVISOR_FIELDS = frozenset(
    {"autonomy", "dream", "learning", "model_query", "supervisor"}
)


def test_composition_root_has_no_supervisor_surface() -> None:
    """PR7a：Composition Root 不 import、构造或返回 Supervisor 对象。"""
    composition_fields = {field.name for field in fields(AgentComposition)}
    assert not composition_fields & _SUPERVISOR_FIELDS

    tree = _tree(BUILDER_PATH)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").lstrip(".").split(".")[0]
            if root in _SUPERVISOR_MODULES:
                violations.append((node.lineno, root))
            for alias in node.names:
                if alias.name in _SUPERVISOR_SYMBOLS:
                    violations.append((node.lineno, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _SUPERVISOR_MODULES:
                    violations.append((node.lineno, alias.name))
        elif isinstance(node, ast.Name) and node.id in _SUPERVISOR_SYMBOLS:
            violations.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in _SUPERVISOR_SYMBOLS:
            violations.append((node.lineno, node.attr))
    assert not violations, f"Composition Root 出现 Supervisor 符号: {violations}"


@pytest.mark.parametrize(
    "path,class_name",
    [
        ("capabilities/plan/runtime.py", "PlanRuntime"),
        ("capabilities/subagent/factory.py", "SubagentFactory"),
    ],
)
def test_domain_runtime_constructors_do_not_receive_whole_agent(path, class_name):
    tree = _tree(SOURCE_ROOT / path)
    init = _method(tree, class_name, "__init__")
    argument_names = {
        argument.arg
        for argument in [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs]
    }
    assert "agent" not in argument_names
