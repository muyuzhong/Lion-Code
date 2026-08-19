"""PR9 旧 Memory/Dream/Learning 删除后的负向架构门禁。"""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

REMOVED_MODULES = (
    "memory.py",
    "dream.py",
    "dream_adapter.py",
    "learning_runtime.py",
    "session_memory.py",
    "session_memory_coordinator.py",
)
REMOVED_DIRECTORIES = ("memory_runtime",)
LEGACY_SYMBOLS = {
    "SessionMemory",
    "SessionMemoryCoordinator",
    "SessionMemoryRepository",
    "SessionMemoryPort",
    "MemoryContextInjector",
    "MemoryCoordinator",
    "MemoryQuerySink",
    "RelevantMemory",
    "DreamCoordinator",
    "DreamAgentFactory",
    "RestrictedDreamAgentFactory",
    "LearningRuntime",
    "_CAP_MEMORY",
    "ProviderTextQueryService",
    "TextQueryService",
}
FUTURE_CAPABILITY_SYMBOLS = {
    "MemoryCapability",
    "MemoryProjectionLayer",
    "MemoryResource",
    "MemorySessionParticipant",
    "MemoryTurnParticipant",
}
CURRENT_ARCHITECTURE_SYMBOLS = LEGACY_SYMBOLS | {
    "MemoryCapability",
    "MemoryProjectionLayer",
    "MemoryResource",
    "MemorySessionParticipant",
    "MemoryTurnParticipant",
    "NoticeSinkAdapter",
    "ProjectionLayer",
    "projection_layers",
}


def _production_files() -> list[Path]:
    return [
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if path != SOURCE_ROOT / "core" / "session" / "memory.py"
    ]


def _relative_source_path(path: Path) -> Path:
    try:
        return path.relative_to(SOURCE_ROOT)
    except ValueError:
        return path


def _symbol_violations(
    path: Path, source: str, forbidden: set[str]
) -> list[tuple[int, str]]:
    tree = ast.parse(source, filename=str(path))
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in forbidden:
                violations.append((node.lineno, node.name))
        elif isinstance(node, ast.Name) and node.id in forbidden:
            violations.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in forbidden:
            violations.append((node.lineno, node.attr))
        elif isinstance(node, ast.alias) and node.name in forbidden:
            violations.append((node.lineno, node.name))
    return violations


def _legacy_symbol_violations(path: Path, source: str) -> list[tuple[int, str]]:
    """识别旧架构符号，同时允许未来 Capability 自己定义 Memory slots。"""

    relative = _relative_source_path(path).as_posix()
    allowed_future_capability = relative.startswith("capabilities/")
    forbidden = set(LEGACY_SYMBOLS)
    if not allowed_future_capability:
        forbidden.update(FUTURE_CAPABILITY_SYMBOLS)
    return _symbol_violations(path, source, forbidden)


def test_removed_modules_are_absent() -> None:
    assert not any((SOURCE_ROOT / name).exists() for name in REMOVED_MODULES)
    assert not any((SOURCE_ROOT / name).exists() for name in REMOVED_DIRECTORIES)


def test_removed_legacy_symbols_are_absent_from_production() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _production_files():
        violations.extend(
            (str(path), lineno, symbol)
            for lineno, symbol in _legacy_symbol_violations(
                path,
                path.read_text(encoding="utf-8"),
            )
        )
    assert not violations, violations


def test_current_product_has_zero_removed_architecture_symbols() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _production_files():
        violations.extend(
            (str(path.relative_to(SOURCE_ROOT)), lineno, symbol)
            for lineno, symbol in _symbol_violations(
                path,
                path.read_text(encoding="utf-8"),
                CURRENT_ARCHITECTURE_SYMBOLS,
            )
        )
    assert violations == []


def test_future_memory_capability_shape_is_not_blocked() -> None:
    source = """
from lion_code.capabilities import CapabilitySpec

class MemoryCapability:
    pass

class MemoryProjectionLayer:
    pass

class MemoryTurnParticipant:
    pass

SPEC = CapabilitySpec(name="memory")
"""
    assert _legacy_symbol_violations(Path("capabilities/memory.py"), source) == []


def test_legacy_scanner_rejects_old_modules_and_coupling_symbols() -> None:
    assert (SOURCE_ROOT / "session_memory_coordinator.py").name in REMOVED_MODULES
    samples = {
        Path("composition/agent_builder.py"): "_CAP_MEMORY = 'memory'",
        Path("runtime/provider.py"): "class ProviderTextQueryService: pass",
        Path("capabilities/memory.py"): "class SessionMemoryCoordinator: pass",
    }
    for path, source in samples.items():
        assert _legacy_symbol_violations(path, source), path


def test_canonical_session_memory_entry_module_remains() -> None:
    path = SOURCE_ROOT / "core" / "session" / "memory.py"
    assert path.is_file()
    assert "CompactionEntry" in path.read_text(encoding="utf-8")
