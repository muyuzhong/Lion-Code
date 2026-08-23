"""一期 Memory Capability 的所有权与延迟副作用门禁。"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import lion_code.composition.agent_builder as agent_builder
from lion_code.capabilities.memory import MemoryStore
from lion_code.composition import (
    AgentConfig,
    FullProfile,
    RuntimeBindings,
    SessionBindings,
    build_agent_composition,
)
from lion_code.project_identity import ProjectIdentity
from lion_code.session_runtime import SessionRepository

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MEMORY_PACKAGE = REPOSITORY_ROOT / "lion_code" / "capabilities" / "memory"
FORBIDDEN_MEMORY_IMPORT_ROOTS = frozenset({"providers", "runtime"})


def _import_roots(tree: ast.Module) -> frozenset[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
    return frozenset(roots)


def _full_composition(tmp_path: Path) -> tuple[object, Path]:
    db_path = tmp_path / "memory.sqlite3"
    provider = Mock()
    provider.aclose = AsyncMock()
    with (
        patch(
            "lion_code.composition.agent_builder.create_provider",
            return_value=provider,
        ),
        patch.object(agent_builder, "default_memory_db_path", lambda: db_path),
        patch.object(
            agent_builder,
            "resolve_project_identity",
            lambda cwd=None: ProjectIdentity(
                root=Path(cwd or tmp_path), key="test-project", is_git=False
            ),
        ),
    ):
        composition = build_agent_composition(
            FullProfile(),
            config=AgentConfig(api_key="test-key", terminal_output=False),
            bindings=RuntimeBindings(
                session=SessionBindings(
                    session_repository=SessionRepository(tmp_path / "sessions")
                )
            ),
        )
    return composition, db_path


def _iter_values(owner: object):
    for value in vars(owner).values():
        yield value
        if isinstance(value, (list, tuple)):
            yield from value


def test_runtime_owners_do_not_hold_memory_store(tmp_path) -> None:
    composition, _db_path = _full_composition(tmp_path)
    runtime = composition.runtime

    for owner in (
        runtime.agent,
        runtime.conversation,
        runtime.session,
        runtime.context,
        runtime.provider_controller,
    ):
        assert not any(
            isinstance(value, MemoryStore) for value in _iter_values(owner)
        ), f"{type(owner).__name__} 不得持有 MemoryStore"


def test_memory_package_stays_local_no_provider_or_runtime_imports() -> None:
    for path in sorted(MEMORY_PACKAGE.glob("*.py")):
        roots = _import_roots(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        assert not roots & FORBIDDEN_MEMORY_IMPORT_ROOTS, path


def test_full_memory_construction_is_lazy_and_uses_ordinary_context_layer(
    tmp_path,
) -> None:
    composition, db_path = _full_composition(tmp_path)

    assert not db_path.exists()
    assert "memory" in {
        layer.layer_id for layer in composition.capabilities.registry.context_layers
    }
    tools = {tool.name for tool in composition.tooling.registry.all_tools()}
    assert {"remember_task", "recall_tasks", "recall_memory"} <= tools
    assert "# Memory Policy" in composition.tooling.prompt_composer.get_system()
