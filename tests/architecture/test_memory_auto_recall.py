"""PR4 自动召回的架构不可达门禁。

证明（对照 PRD 验收标准）：
1. Runtime 各 owner 不持有 ``MemoryStore``（CapabilityRegistry 只聚合投影，
   存储只由 Capability 内部 tool/query adapter 持有）；
2. memory capability 包不依赖 providers/runtime——自动召回是本地同步
   SQLite 查询，不存在第二次 LLM/Provider 调用路径；
3. 自动召回输出只进本次 prepared provider context：不写 canonical
   ConversationRuntime messages，也不写 Session JSONL。
"""

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
from lion_code.core import UserMessage
from lion_code.project_identity import ProjectIdentity
from lion_code.session_runtime import SessionRepository

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MEMORY_PACKAGE = REPOSITORY_ROOT / "lion_code" / "capabilities" / "memory"
# Runtime 层禁止依赖的根（providers/runtime）
FORBIDDEN_MEMORY_IMPORT_ROOTS = frozenset({"providers", "runtime"})


def _import_roots(tree: ast.Module) -> frozenset[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
    return frozenset(roots)


def _full_composition(tmp_path: Path) -> tuple[object, MemoryStore]:
    """构造 hermetic 的 Full 组合：DB 与 project identity 都指向临时目录。"""
    db_path = tmp_path / "memory.sqlite3"
    store = MemoryStore(db_path, project_key="test-project")
    store.remember(
        kind="definition",
        scope="project",
        stable_key="db-paths",
        content="database paths live in config/db.py",
        evidence=["config/db.py"],
    )
    provider = Mock()
    provider.aclose = AsyncMock()
    with (
        patch(
            "lion_code.composition.agent_builder.create_provider",
            return_value=provider,
        ),
        patch.object(
            agent_builder,
            "default_memory_db_path",
            lambda: db_path,
        ),
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
    return composition, store


def _iter_values(owner: object):
    for value in vars(owner).values():
        yield value
        if isinstance(value, (list, tuple)):
            yield from value


def test_runtime_owners_do_not_hold_memory_store(tmp_path) -> None:
    composition, _store = _full_composition(tmp_path)
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
        assert (
            not _import_roots(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
            & FORBIDDEN_MEMORY_IMPORT_ROOTS
        ), path


def test_auto_recall_is_prepared_only_not_canonical_or_jsonl(tmp_path) -> None:
    import asyncio

    composition, _store = _full_composition(tmp_path)
    context_runtime = composition.runtime.context
    conversation = composition.runtime.conversation

    canonical = [UserMessage(content="where do the database paths live?")]
    conversation.harness.replace_messages(list(canonical))
    prepared = asyncio.run(
        context_runtime.prepare_context(list(conversation.harness.messages))
    )

    assert "# Active Memory" in prepared[-1].text
    # 不写 canonical ConversationRuntime messages，不产生任何 Session JSONL
    assert all("Active Memory" not in m.text for m in conversation.harness.messages)
    assert conversation.harness.messages[0] is canonical[0]
    assert list((tmp_path / "sessions").glob("*.jsonl")) == []
