"""PR9 旧 Memory/Dream/Learning 删除后的负向架构门禁。"""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

REMOVED_MODULES = (
    "memory.py",
    "capabilities/memory.py",
    "dream.py",
    "dream_adapter.py",
    "learning_runtime.py",
    "session_memory.py",
    "session_memory_coordinator.py",
)
REMOVED_DIRECTORIES = ("memory_runtime",)
FORBIDDEN_SYMBOLS = {
    "SessionMemory",
    "SessionMemoryCoordinator",
    "SessionMemoryRepository",
    "SessionMemoryPort",
    "MemoryCapability",
    "MemoryContextInjector",
    "MemoryCoordinator",
    "MemoryProjectionLayer",
    "MemoryResource",
    "MemorySessionParticipant",
    "MemoryTurnParticipant",
    "MemoryQuerySink",
    "RelevantMemory",
    "DreamCoordinator",
    "DreamAgentFactory",
    "RestrictedDreamAgentFactory",
    "LearningRuntime",
    "_CAP_MEMORY",
    "ProjectionLayer",
    "projection_layers",
    "NoticeSinkAdapter",
    "ProviderTextQueryService",
    "TextQueryService",
}


def _production_files() -> list[Path]:
    return [
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if path != SOURCE_ROOT / "core" / "session" / "memory.py"
    ]


def test_removed_modules_are_absent() -> None:
    assert not any((SOURCE_ROOT / name).exists() for name in REMOVED_MODULES)
    assert not any(
        path.is_file()
        for name in REMOVED_DIRECTORIES
        for path in (SOURCE_ROOT / name).rglob("*.py")
    )


def test_removed_symbols_and_projection_slot_are_absent_from_production() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_SYMBOLS:
                violations.append((str(path), node.lineno, node.id))
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_SYMBOLS:
                violations.append((str(path), node.lineno, node.attr))
            elif isinstance(node, ast.alias) and node.name in FORBIDDEN_SYMBOLS:
                violations.append((str(path), node.lineno, node.name))
    assert not violations, violations


def test_canonical_session_memory_entry_module_remains() -> None:
    path = SOURCE_ROOT / "core" / "session" / "memory.py"
    assert path.is_file()
    assert "CompactionEntry" in path.read_text(encoding="utf-8")
