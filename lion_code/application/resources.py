"""资源诊断轻类型(vendored 自 tau_coding/resources.py 的子集)。

Lion 的资源发现逻辑在 lion_code.capabilities.skill.discovery / lion_code.prompt;本模块只提供
TUI 与命令层需要的诊断数据类型,不引入 Tau 的资源目录体系。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ResourceError(ValueError):
    """Raised when resources are invalid or cannot be expanded."""


@dataclass(frozen=True, slots=True)
class ResourceDiagnostic:
    """A non-fatal resource discovery problem or precedence note."""

    kind: str
    message: str
    path: Path | None = None
    name: str | None = None
    severity: str = "warning"

    def format(self) -> str:
        """Return a concise human-readable diagnostic line."""
        parts = [self.severity, self.kind]
        if self.name is not None:
            parts.append(self.name)
        label = " ".join(parts)
        if self.path is None:
            return f"{label}: {self.message}"
        return f"{label}: {self.message} ({self.path})"
