"""内部工具访问 Agent 状态时使用的受限上下文。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.cancellation import CancellationView
from ..permission_state import PermissionView
from .types import JSONValue, ToolResult

if TYPE_CHECKING:
    from ..runtime.session_identity import SessionView
    from .audit import ExecutionAuditLog
    from .registry import ToolRegistry
    from .types import LionTool


@dataclass(slots=True)
class ToolContext:
    """单个 Agent 的工具执行状态；Registry 激活状态不会跨实例共享。"""

    session: SessionView
    cancellation: CancellationView
    cwd: Path
    registry: ToolRegistry
    permission: PermissionView
    read_file_state: dict[str, float]
    confirm_fn: Callable[[str], Awaitable[bool]] | None = None
    hooks: list[Any] = field(default_factory=list)
    confirm_hook_trust: Callable[[str], Awaitable[bool]] | None = None
    audit_fn: (
        Callable[
            [LionTool, Mapping[str, JSONValue], ToolResult],
            Awaitable[None] | None,
        ]
        | None
    ) = None
    audit_log: ExecutionAuditLog | None = None
