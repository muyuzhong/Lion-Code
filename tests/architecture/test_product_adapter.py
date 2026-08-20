"""PR4 Product Adapter / Feature Cohesion 的九条结构门禁。"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import patch

import lion_code
from lion_code.adapters.coding_session_backend import CodingSessionBackendAdapter
from lion_code.application.ports import CodingSessionBackend
from lion_code.composition import (
    AgentConfig,
    CodingProfile,
    FullProfile,
    MinimalProfile,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
)
from lion_code.meta_agent import MetaAgent, build_profile_agent
from lion_code.composition.full_product import build_full_coding_backend
from lion_code.session_runtime import SessionRepository

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
ADAPTER_PATH = SOURCE_ROOT / "adapters" / "coding_session_backend.py"
PRODUCT_BOOTSTRAP_PATH = SOURCE_ROOT / "composition" / "full_product.py"

_FEATURE_NAMES = frozenset({"plan", "skill", "subagent"})
_META_PRODUCT_METHODS = frozenset(
    {
        "list_sessions",
        "restore_latest",
        "show_cost",
        "set_terminal_output",
        "toggle_plan_mode",
        "set_plan_approval_fn",
        "set_notice_fn",
        "set_confirm_fn",
        "_migrate_legacy_core_session",
    }
)
_FEATURE_FILES = {
    "capabilities/plan/__init__.py",
    "capabilities/plan/capability.py",
    "capabilities/plan/runtime.py",
    "capabilities/skill/__init__.py",
    "capabilities/skill/capability.py",
    "capabilities/skill/runtime.py",
    "capabilities/skill/discovery.py",
    "capabilities/subagent/__init__.py",
    "capabilities/subagent/capability.py",
    "capabilities/subagent/runtime.py",
    "capabilities/subagent/factory.py",
    "capabilities/subagent/types.py",
}
_OLD_FEATURE_PATHS = {
    "agent.py",
    "plan_runtime.py",
    "skill_runtime.py",
    "skills.py",
    "subagent.py",
    "subagent_factory.py",
    "subagent_runtime.py",
}
_SPI_PATHS = (
    SOURCE_ROOT / "capabilities" / "__init__.py",
    SOURCE_ROOT / "capabilities" / "types.py",
    SOURCE_ROOT / "capabilities" / "registry.py",
    SOURCE_ROOT / "capabilities" / "runtime.py",
)


class _FakeProvider:
    async def aclose(self) -> None:
        return None


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_targets(tree: ast.Module) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.add(node.module or "")
            targets.update(alias.name for alias in node.names)
    return targets


def test_public_package_has_no_agent_facade() -> None:
    assert "Agent" not in lion_code.__all__
    assert not hasattr(lion_code, "Agent")
    assert not (SOURCE_ROOT / "agent.py").exists()


def test_product_adapter_satisfies_application_port(tmp_path) -> None:
    repository = SessionRepository(tmp_path / "sessions")
    with patch(
        "lion_code.composition.full_product.create_provider",
        return_value=_FakeProvider(),
    ):
        backend = build_full_coding_backend(
            api_key="test-key",
            terminal_output=False,
            session_repository=repository,
        )
    try:
        assert isinstance(backend, CodingSessionBackend)
    finally:
        asyncio.run(backend.aclose())


def test_product_adapter_does_not_inherit_meta_agent() -> None:
    assert not issubclass(CodingSessionBackendAdapter, MetaAgent)
    assert MetaAgent not in CodingSessionBackendAdapter.__mro__


def test_product_factory_lives_in_composition_bootstrap() -> None:
    adapter_tree = _tree(ADAPTER_PATH)
    adapter_functions = {
        node.name
        for node in ast.walk(adapter_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "build_full_coding_backend" not in adapter_functions
    assert not {
        alias.name
        for node in ast.walk(adapter_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name
        in {
            "AgentConfig",
            "FullProfile",
            "RuntimeBindings",
            "ProviderBindings",
            "SessionBindings",
            "ToolBindings",
            "build_agent_composition",
        }
    }

    bootstrap_tree = _tree(PRODUCT_BOOTSTRAP_PATH)
    bootstrap_functions = {
        node.name
        for node in ast.walk(bootstrap_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "build_full_coding_backend" in bootstrap_functions
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_agent_composition"
        for node in ast.walk(bootstrap_tree)
    )


def test_meta_agent_has_no_product_session_or_ui_methods() -> None:
    meta_agent = next(
        node
        for node in _tree(SOURCE_ROOT / "meta_agent.py").body
        if isinstance(node, ast.ClassDef) and node.name == "MetaAgent"
    )
    methods = {
        node.name
        for node in meta_agent.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not methods & _META_PRODUCT_METHODS


def test_generic_capability_spi_has_no_feature_import_or_branch() -> None:
    violations: dict[str, set[str]] = {}
    for path in _SPI_PATHS:
        tree = _tree(path)
        imports = {
            target
            for target in _import_targets(tree)
            if set(target.split(".")) & _FEATURE_NAMES
        }
        branches = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in _FEATURE_NAMES
        }
        if imports or branches:
            violations[str(path.relative_to(SOURCE_ROOT))] = imports | branches
    assert not violations


def test_feature_implementations_are_cohesive_and_old_paths_are_deleted() -> None:
    actual = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in (SOURCE_ROOT / "capabilities").rglob("*.py")
        if path.relative_to(SOURCE_ROOT).parts[1:2]
        and path.relative_to(SOURCE_ROOT).parts[1] in {"plan", "skill", "subagent"}
    }
    assert actual == _FEATURE_FILES
    assert not any((SOURCE_ROOT / path).exists() for path in _OLD_FEATURE_PATHS)


def test_application_and_tui_do_not_import_harness_directly() -> None:
    violations: dict[str, set[str]] = {}
    for package in ("application", "tui"):
        for path in (SOURCE_ROOT / package).rglob("*.py"):
            tree = _tree(path)
            found: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "harness" in module.casefold():
                        found.add(module)
                    found.update(
                        alias.name
                        for alias in node.names
                        if alias.name in {"AgentHarness", "LionAgentRuntime"}
                    )
                elif isinstance(node, ast.Import):
                    found.update(
                        alias.name
                        for alias in node.names
                        if "harness" in alias.name.casefold()
                    )
                elif isinstance(node, ast.Name) and node.id in {
                    "AgentHarness",
                    "LionAgentRuntime",
                }:
                    found.add(node.id)
            if found:
                violations[path.relative_to(SOURCE_ROOT).as_posix()] = found
    assert not violations


def test_supervisor_does_not_import_product_adapter() -> None:
    imports = _import_targets(_tree(SOURCE_ROOT / "supervisor.py"))
    assert not {
        target
        for target in imports
        if target == "lion_code.adapters" or target.startswith("lion_code.adapters.")
    }


def test_profiles_build_one_meta_agent_and_one_runtime_shape(tmp_path) -> None:
    profiles = (MinimalProfile(), CodingProfile(), FullProfile())
    agents = []
    runtime_shapes = []
    try:
        for index, profile in enumerate(profiles):
            provider = _FakeProvider()
            agent = build_profile_agent(
                profile,
                config=AgentConfig(api_key="test-key", terminal_output=False),
                bindings=RuntimeBindings(
                    provider=ProviderBindings(provider=provider),
                    session=SessionBindings(
                        session_repository=SessionRepository(
                            tmp_path / f"sessions-{index}"
                        )
                    ),
                ),
            )
            agents.append(agent)
            runtime_shapes.append(
                (
                    type(agent._agent_runtime),
                    type(agent._agent_runtime._context),
                    type(agent._conversation),
                    type(agent._session),
                    type(agent._provider_controller),
                )
            )
    finally:
        for agent in agents:
            asyncio.run(agent.close())

    assert all(type(agent) is MetaAgent for agent in agents)
    assert runtime_shapes[0] == runtime_shapes[1] == runtime_shapes[2]
