"""私有 verifier 的结果归一化边界；foundation 不在 host 执行 hidden 命令。"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

from .backend import VerifierExecutionRequest
from .models import VerifierOutcome, VerifierResult
from .trace import redact_text


VerifierRunner = Callable[[VerifierExecutionRequest], Awaitable[VerifierResult]]


def normalize_verifier_result(
    *,
    outcome: VerifierOutcome,
    command_summary: str,
    exit_code: int,
    output: str,
) -> VerifierResult:
    """将 private verifier 输出压缩为无敏感正文的稳定结果。"""

    safe_command, _ = redact_text(command_summary, max_length=320)
    safe_output, _ = redact_text(output, max_length=320)
    return VerifierResult(
        outcome=outcome,
        command_summary=safe_command,
        exit_code=exit_code,
        output_digest=hashlib.sha256(output.encode("utf-8")).hexdigest(),
        output_preview=safe_output,
    )


async def run_verifier(
    request: VerifierExecutionRequest,
    *,
    runner: VerifierRunner,
) -> VerifierResult:
    """委托已隔离的 verifier runner；该函数不读取 Agent workspace 或执行 shell。"""

    return await runner(request)
