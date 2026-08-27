"""命令执行后端：把 shell 命令执行从工具定义中抽出的最窄 seam。"""

from __future__ import annotations

import subprocess
from typing import Protocol

DEFAULT_TIMEOUT_MS = 30000.0


class CommandExecutionBackend(Protocol):
    """执行单条 shell 命令并返回文本输出的最窄契约。

    Profile 选择的 backend 在 Composition Root 绑定到 ``run_shell``；
    测试可注入 fake backend 隔离真实进程副作用。
    """

    def run(
        self,
        command: str,
        *,
        timeout_ms: float = DEFAULT_TIMEOUT_MS,
    ) -> str: ...


class LocalCommandExecutionBackend:
    """本地 subprocess shell 语义，保持既有输出/超时/错误文本契约。"""

    def run(
        self,
        command: str,
        *,
        timeout_ms: float = DEFAULT_TIMEOUT_MS,
    ) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000,
                stdin=subprocess.DEVNULL,
            )
            output = result.stdout or ""
            if result.returncode != 0:
                stderr = f"\nStderr: {result.stderr}" if result.stderr else ""
                stdout = f"\nStdout: {result.stdout}" if result.stdout else ""
                return f"Command failed (exit code {result.returncode}){stdout}{stderr}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {int(timeout_ms)}ms"
        except Exception as e:
            return f"Error: {e}"


__all__ = [
    "DEFAULT_TIMEOUT_MS",
    "CommandExecutionBackend",
    "LocalCommandExecutionBackend",
]
