"""大工具结果的完整持久化与上下文预览策略。"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from .types import LionTool, ToolResult


MAX_RESULT_CHARS = 50_000
DEFAULT_PERSIST_THRESHOLD = 30 * 1024


def truncate_result(result: str, max_chars: int = MAX_RESULT_CHARS) -> str:
    """以头尾保留方式限制单个上下文结果的字符数。"""
    if len(result) <= max_chars:
        return result
    keep_each = (max_chars - 60) // 2
    return (
        result[:keep_each]
        + f"\n\n[... truncated {len(result) - keep_each * 2} chars ...]\n\n"
        + result[-keep_each:]
    )


class ResultStore:
    """先保存完整结果，再生成包含可回读路径的有界预览。"""

    def __init__(
        self,
        root: Path | None = None,
        *,
        threshold_bytes: int = DEFAULT_PERSIST_THRESHOLD,
        preview_lines: int = 200,
    ) -> None:
        self.root = root or Path.home() / ".lion-code" / "tool-results"
        self.threshold_bytes = threshold_bytes
        self.preview_lines = preview_lines

    def process(self, tool: LionTool, result: ToolResult) -> ToolResult:
        """按照工具声明处理结果；错误和 normal 结果不自动落盘。"""
        original = result.content
        original_bytes = len(original.encode("utf-8"))
        if (
            result.is_error
            or tool.capabilities.result_policy == "normal"
            or original_bytes <= self.threshold_bytes
        ):
            return result

        self.root.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", tool.name).strip("-")
        filename = (
            f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}-"
            f"{safe_name or 'tool'}.txt"
        )
        path = self.root / filename
        path.write_text(original, encoding="utf-8")

        lines = original.split("\n")
        preview = "\n".join(lines[: self.preview_lines])
        size_kb = original_bytes / 1024
        content = truncate_result(
            f"[Result too large ({size_kb:.1f} KB, {len(lines)} lines). "
            f"Full output saved to {path}. "
            "You can use read_file to see the full result.]\n\n"
            f"Preview (first {self.preview_lines} lines):\n{preview}"
        )
        return ToolResult(
            content=content,
            is_error=result.is_error,
            details={
                **result.details,
                "persisted_path": str(path),
                "original_bytes": original_bytes,
                "result_policy": tool.capabilities.result_policy,
            },
            activated_tools=list(result.activated_tools),
            terminate=result.terminate,
        )
