"""Composition Root 与 Capability 扩展面的架构验收。"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from lion_code.agent import Agent
from lion_code.capabilities.types import CapabilitySpec
from lion_code.composition import AgentConfig, AgentDependencies
from lion_code.tooling.environment import ToolEnvironment
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


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name):
            names.add(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            names.add(call.func.attr)
    return names


def test_config_and_dependencies_are_separate_frozen_values() -> None:
    config = AgentConfig()
    dependencies = AgentDependencies()

    with pytest.raises(FrozenInstanceError):
        config.model = "mutated"
    with pytest.raises(FrozenInstanceError):
        dependencies.extra_capabilities = ()

    config_fields = {field.name for field in fields(config)}
    dependency_fields = {field.name for field in fields(dependencies)}
    assert "tool_registry" not in config_fields
    assert "context_manager" not in config_fields
    assert "model" not in dependency_fields
    assert "permission_mode" not in dependency_fields


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
        mcp_enabled=False,
    )
    dependencies = AgentDependencies(
        tool_registry=ToolRegistry(),
        tool_environment=ToolEnvironment(owns_mcp_manager=False),
        extra_capabilities=(spec,),
    )
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch("lion_code.agent.create_provider", return_value=provider):
        agent = Agent(config=config, dependencies=dependencies)

    assert "example" in agent._capability_registry.names
    assert "example capability prompt" in agent._prompt_composer.get_system()
    await agent.clear_history()
    assert participant.new_sessions == 1
    await agent.close()


def test_agent_constructor_delegates_to_the_composition_root():
    tree = _tree(SOURCE_ROOT / "agent.py")
    constructor = _method(tree, "Agent", "__init__")
    called = _called_names(constructor)
    assert "build_agent_composition" in called
    assert (
        not {
            "PermissionController",
            "PermissionState",
            "SessionIdentityState",
            "ExecutionControl",
            "UsageLedger",
            "BudgetPolicy",
            "PlanRuntime",
            "ProviderManager",
            "AgentRuntimeCoordinator",
            "SessionMemoryCoordinator",
            "AutonomyRuntime",
            "LearningRuntime",
            "SubagentFactory",
            "CapabilityRegistry",
            "ToolRuntime",
        }
        & called
    )


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
        for node in ast.walk(_tree(SOURCE_ROOT / "agent.py"))
    )


@pytest.mark.parametrize(
    "path,class_name",
    [
        ("autonomy_runtime.py", "AutonomyRuntime"),
        ("learning_runtime.py", "LearningRuntime"),
        ("session_memory_coordinator.py", "SessionMemoryCoordinator"),
        ("plan_runtime.py", "PlanRuntime"),
        ("subagent_factory.py", "SubagentFactory"),
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
