"""Semantic Memory feature：SQLite 存储、revision 生命周期与治理工具。

PR3 范围：存储层 + 显式工具面（经 Capability ToolSource 注册）。
自动召回（QueryContextLayer / FullProfile 默认启用）属 PR4。
"""

from .capability import create_memory_capability
from .store import (
    ManageAction,
    MemoryEntry,
    MemoryHit,
    MemoryKind,
    MemoryRecallMode,
    MemoryScope,
    MemoryStatus,
    MemoryStore,
    MemoryStoreError,
    ReviewReport,
    ReviewStaleCandidate,
    RevisionChain,
    default_memory_db_path,
)

__all__ = [
    "ManageAction",
    "MemoryEntry",
    "MemoryHit",
    "MemoryKind",
    "MemoryRecallMode",
    "MemoryScope",
    "MemoryStatus",
    "MemoryStore",
    "MemoryStoreError",
    "ReviewReport",
    "ReviewStaleCandidate",
    "RevisionChain",
    "create_memory_capability",
    "default_memory_db_path",
]
