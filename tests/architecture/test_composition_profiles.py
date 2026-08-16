"""PR7c Composition Profile Layer：三种 Profile 的真实对象图与结构门禁。

验收：
1. MinimalProfile 实际图只含 caller tools，CapabilityRegistry 为空，facade 为 MetaAgent。
2. CodingProfile 实际图含 backend 绑定的 Coding 工具与 Meta facade；Skill 只随
   SkillComposition 出现。
3. FullProfile 实际图含 Memory/Plan/SubAgent/默认 Skill/extension specs，Capability
   prompt layers 进入同一 PromptComposer。
4. Profile 是 frozen/slots 纯值对象：无 feature bool、运行时方法或 registry lookup。
5. Kernel/Harness 不 import Profile，Feature branch 只存在于 Composition Root。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from lion_code.agent import Agent
from lion_code.composition import (
    NEUTRAL_SYSTEM_PROMPT,
    AgentConfig,
    AgentDependencies,
    CodingProfile,
    FullProfile,
    MinimalProfile,
    ProductFacadeKind,
    SkillComposition,
    build_agent_composition,
)
from lion_code.composition.agent_builder import _normalize_profile
from lion_code.meta_agent import MetaAgent, build_coding_agent, build_meta_agent
from lion_code.prompt import build_static_system_prompt
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.builtin import BUILTIN_TOOL_NAMES
from lion_code.tooling.execution import LocalCommandExecutionBackend
from lion_code.tooling.permission import PermissionDecision, PermissionPolicy
from lion_code.tooling.types import LionTool, ToolResult

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"
PROFILES_PATH = SOURCE_ROOT / "composition" / "profiles.py"
SUBAGENT_FACTORY_PATH = SOURCE_ROOT / "subagent_factory.py"

_PROFILE_CLASSES = ("MinimalProfile", "CodingProfile", "FullProfile")


class _RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def run(self, command: str, *, timeout_ms: float = 30000.0) -> str:
        self.calls.append((command, timeout_ms))
        return f"backend-ran: {command}"


class _AllowAllStrategy:
    """验证 identity 传递的最小 ToolPermissionStrategy 实现。"""

    def check_hard_boundaries(self, *, tool, arguments, mode):
        return None

    def check(self, *, tool, arguments, mode):
        return PermissionDecision("allow")


async def _noop_execute(_context, _tool_call_id, _arguments, _on_update):
    return ToolResult(content="ok")


def _tool(name: str) -> LionTool:
    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=_noop_execute,
    )


def _fake_provider():
    provider = Mock()
    provider.aclose = AsyncMock()
    return provider


def _minimal(tmp_path, monkeypatch, **profile_kwargs) -> object:
    monkeypatch.chdir(tmp_path)
    profile_kwargs.setdefault(
        "config", AgentConfig(api_key="test-key", terminal_output=False)
    )
    profile_kwargs.setdefault("dependencies", AgentDependencies())
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=_fake_provider(),
    ):
        return build_agent_composition(MinimalProfile(**profile_kwargs))


def test_minimal_graph_only_contains_caller_tools(tmp_path, monkeypatch) -> None:
    composition = _minimal(
        tmp_path,
        monkeypatch,
        tools=(_tool("caller_a"), _tool("caller_b")),
    )

    assert {tool.name for tool in composition.tool_registry.all_tools()} == {
        "caller_a",
        "caller_b",
    }
    assert composition.capability_registry.names == ()
    assert composition.plan is None
    assert composition.subagent_factory is None
    assert composition.subagent_executor is None
    assert composition.skill_runtime is None
    assert composition.session_memory_coordinator is None
    assert composition.status_sink is None
    assert composition.facade is ProductFacadeKind.META
    assert NEUTRAL_SYSTEM_PROMPT in composition.prompt_composer.get_system()


def test_coding_graph_binds_backend_and_default_capabilities(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    backend = _RecordingBackend()
    strategy = _AllowAllStrategy()
    profile = CodingProfile(
        config=AgentConfig(
            api_key="test-key",
            permission_mode="bypassPermissions",
            terminal_output=False,
        ),
        dependencies=AgentDependencies(),
        command_backend=backend,
        permission_strategy=strategy,
        extra_tools=(_tool("extra_tool"),),
    )
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=_fake_provider(),
    ):
        composition = build_agent_composition(profile)

    names = {tool.name for tool in composition.tool_registry.all_tools()}
    assert BUILTIN_TOOL_NAMES <= names
    assert {"tool_search", "extra_tool"} <= names
    assert composition.capability_registry.names == ()
    assert composition.skill_runtime is None
    assert composition.plan is None
    assert composition.session_memory_coordinator is None
    assert composition.facade is ProductFacadeKind.META
    assert composition.permission_policy is strategy

    result = asyncio.run(
        composition.tool_runtime.execute(
            tool_call_id="call-1",
            name="run_shell",
            arguments={"command": "echo hi", "timeout": 1200},
        )
    )
    assert backend.calls == [("echo hi", 1200.0)]
    assert result.content == "backend-ran: echo hi"
    assert build_static_system_prompt() in composition.prompt_composer.get_system()


def test_coding_graph_composes_skill_only_with_skill_composition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    profile = CodingProfile(
        config=AgentConfig(api_key="test-key", terminal_output=False),
        dependencies=AgentDependencies(),
        skill=SkillComposition(),
    )
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=_fake_provider(),
    ):
        composition = build_agent_composition(profile)

    assert set(composition.capability_registry.names) == {"skill", "subagent"}
    assert composition.skill_runtime is not None
    assert composition.subagent_executor is not None
    # Coding 不构造 Full-only Capability。
    assert composition.plan is None
    assert composition.session_memory_coordinator is None


class _ExamplePromptLayer:
    layer_id = "example"

    def render(self) -> str:
        return "example extension prompt layer"


def test_full_graph_contains_memory_plan_subagent_skill_and_extensions(
    tmp_path, monkeypatch
):
    from lion_code.capabilities.types import CapabilitySpec

    monkeypatch.chdir(tmp_path)
    backend = _RecordingBackend()
    strategy = _AllowAllStrategy()
    spec = CapabilitySpec(
        name="example-extension",
        prompt_layers=(_ExamplePromptLayer(),),
    )
    profile = FullProfile(
        config=AgentConfig(api_key="test-key", terminal_output=False),
        dependencies=AgentDependencies(session_repository=_repo(tmp_path)),
        command_backend=backend,
        permission_strategy=strategy,
        extension_specs=(spec,),
    )
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=_fake_provider(),
    ):
        composition = build_agent_composition(profile)

    assert set(composition.capability_registry.names) >= {
        "skill",
        "subagent",
        "plan",
        "memory",
        "example-extension",
    }
    assert composition.plan is not None
    assert composition.subagent_factory is not None
    assert composition.skill_runtime is not None
    assert composition.session_memory_coordinator is not None
    assert composition.status_sink is not None
    assert composition.facade is ProductFacadeKind.FULL
    assert composition.permission_policy is strategy
    system = composition.prompt_composer.get_system()
    assert build_static_system_prompt() in system
    assert "example extension prompt layer" in system
    assert "# Environment" in system


def _repo(tmp_path: Path) -> SessionRepository:
    return SessionRepository(tmp_path / "sessions")


def test_profile_types_reject_capability_name_sets() -> None:
    """公共 Profile 不接受任意 capability-name set（结构上无该字段）。"""
    from dataclasses import fields

    for profile_type in (MinimalProfile, CodingProfile, FullProfile):
        field_names = {field.name for field in fields(profile_type)}
        assert "capabilities" not in field_names
        assert not field_names & {"skill_enabled", "memory_enabled", "plan_enabled"}


def test_full_agent_facade_uses_full_profile_and_child_uses_coding_profile(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    with (
        patch("lion_code.agent.create_provider", return_value=_fake_provider()),
        patch(
            "lion_code.composition.agent_builder.create_provider",
            return_value=_fake_provider(),
        ),
    ):
        agent = Agent(
            api_key="test-key",
            session_repository=_repo(tmp_path),
            terminal_output=False,
        )
        child = agent._subagent_factory.create_for_agent_type("general")  # noqa: SLF001

    try:
        assert isinstance(agent, Agent)
        assert isinstance(child, MetaAgent)
        assert not isinstance(child, Agent)
        assert child.permission_mode == "bypassPermissions"
    finally:
        asyncio.run(child.close())
        asyncio.run(agent.close())


def test_build_meta_agent_and_build_coding_agent_return_meta_facade(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    provider = _fake_provider()
    meta = build_meta_agent(
        provider=provider,
        tools=[_tool("caller_tool")],
        session_repository=_repo(tmp_path),
    )
    assert isinstance(meta, MetaAgent)
    assert meta.run_once is not None

    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=_fake_provider(),
    ):
        coding = build_coding_agent(
            api_key="test-key",
            terminal_output=False,
            system_prompt="custom coding prompt",
        )
    assert isinstance(coding, MetaAgent)
    asyncio.run(meta.close())
    asyncio.run(coding.close())


def test_subagent_factory_reuses_coding_composition_entrypoint() -> None:
    """子 Agent 必须经 CodingProfile 进入唯一 Composition Root。"""

    tree = ast.parse(
        SUBAGENT_FACTORY_PATH.read_text(encoding="utf-8"),
        filename=str(SUBAGENT_FACTORY_PATH),
    )
    imports = {
        (node.level, node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    assert (1, "meta_agent", "build_coding_agent") in imports
    assert not {
        (level, module)
        for level, module, _name in imports
        if level == 1 and module in {"agent", "agent_runtime"}
    }
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_coding_agent"
        for node in ast.walk(tree)
    )


# ---------------------------------------------------------------------------
# Profile 结构门禁（AST）
# ---------------------------------------------------------------------------


def test_profiles_are_frozen_slots_value_objects() -> None:
    tree = ast.parse(PROFILES_PATH.read_text(encoding="utf-8"))
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in _PROFILE_CLASSES
    }
    assert set(classes) == set(_PROFILE_CLASSES)

    for name, node in classes.items():
        decorators = {
            ast.unparse(d) for d in node.decorator_list if isinstance(d, ast.Call)
        }
        assert any("frozen=True" in d and "slots=True" in d for d in decorators), name

        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert member.name == "__post_init__", (
                    f"{name} 定义了运行时方法: {member.name}"
                )

        field_types = {
            member.target.id: ast.unparse(member.annotation)
            for member in node.body
            if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name)
        }
        for field_name, annotation in field_types.items():
            assert "bool" not in annotation, f"{name}.{field_name} 是 feature bool"
            assert "frozenset[str]" not in annotation, (
                f"{name}.{field_name} 接受 capability-name set"
            )


def test_profiles_do_not_expose_builders_or_lookups() -> None:
    source = PROFILES_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in {"build", "get", "resolve", "create", "services"}


def test_kernel_and_harness_do_not_import_profiles() -> None:
    scanned = [
        *sorted((SOURCE_ROOT / "core").rglob("*.py")),
        *sorted((SOURCE_ROOT / "context").rglob("*.py")),
        *sorted((SOURCE_ROOT / "tooling").rglob("*.py")),
        *sorted((SOURCE_ROOT / "providers").rglob("*.py")),
        *sorted((SOURCE_ROOT / "session_runtime").rglob("*.py")),
        *sorted((SOURCE_ROOT / "observers").rglob("*.py")),
        *sorted((SOURCE_ROOT / "adapters").rglob("*.py")),
        SOURCE_ROOT / "agent_runtime.py",
        SOURCE_ROOT / "session_lifecycle.py",
        SOURCE_ROOT / "provider_manager.py",
    ]
    for path in scanned:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "profiles" not in node.module, path
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "profiles" not in alias.name, path
            elif isinstance(node, ast.Attribute):
                assert node.attr not in _PROFILE_CLASSES, path
            elif isinstance(node, ast.Name):
                assert node.id not in _PROFILE_CLASSES, path


def test_feature_construction_branches_live_only_in_normalize_profile() -> None:
    """Capability 构造分支只允许出现在 Composition Root 的构造 helper 内。"""
    builder_path = SOURCE_ROOT / "composition" / "agent_builder.py"
    tree = ast.parse(builder_path.read_text(encoding="utf-8"))
    capability_typed_fields = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id.startswith("_CAP_")
    }
    assert capability_typed_fields, "CAP 选择常量缺失"

    composition_helpers = {
        "_normalize_profile",
        "_build_capability_graph",
        "_build_session_graph",
        "_build_foundation",
        "_resolve_dependencies",
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in composition_helpers:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id in capability_typed_fields:
                raise AssertionError(f"Feature branch 泄漏到 {node.name}: {inner.id}")


def test_local_backend_is_default_and_protocol_matches() -> None:
    profile = FullProfile(
        config=AgentConfig(api_key="test-key"),
        dependencies=AgentDependencies(),
    )
    assert isinstance(profile.command_backend, LocalCommandExecutionBackend)
    selection = _normalize_profile(profile)
    assert selection.command_backend is profile.command_backend

    minimal = MinimalProfile(
        config=AgentConfig(api_key="test-key"),
        dependencies=AgentDependencies(),
    )
    selection = _normalize_profile(minimal)
    assert selection.command_backend is None
    assert selection.builtin_tools is False


def test_permission_policy_satisfies_strategy_protocol() -> None:
    """现有 PermissionPolicy 结构化实现 ToolPermissionStrategy 契约。"""
    from lion_code.tooling.middleware import PermissionMiddleware

    policy = PermissionPolicy()
    assert callable(policy.check_hard_boundaries)
    assert callable(policy.check)
    assert "policy" in PermissionMiddleware.__init__.__annotations__
