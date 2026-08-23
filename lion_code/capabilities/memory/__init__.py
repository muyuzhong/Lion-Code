"""Semantic Memory feature：SQLite 存储、revision 生命周期、治理工具与自动召回。

PR3：存储层 + 显式工具面（经 Capability ToolSource 注册）。
PR4：QueryContextLayer 自动召回 + FullProfile 默认启用。
"""

from .capability import create_memory_capability
from .query_layer import AUTHORITY_NOTE, MemoryQueryContextLayer
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
    "AUTHORITY_NOTE",
    "ManageAction",
    "MemoryEntry",
    "MemoryHit",
    "MemoryKind",
    "MemoryQueryContextLayer",
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
