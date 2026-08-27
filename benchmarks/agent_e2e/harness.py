"""官方 SWE-bench Harness 复核的 fixture 解析与结果归一化。

这里的 Harness adapter 只接受固定版本的受控 JSON；不会执行 evaluator。只有
Linux 阶段提供真实、隔离且 ``supports_official_scores`` 的 runner 后，调用方才
能把归一化结果提升为 ``TaskResult.official=True``。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    AdapterStatus,
    AgentRunSummary,
    ExperimentManifest,
    FailureSource,
    HarnessRecheckResult,
    ResultValidity,
    TaskResult,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)
from .trace import redact_text

HARNESS_RESULT_SCHEMA_VERSION = "swebench-harness-result/v1"


class HarnessResultError(ValueError):
    """Harness result fixture 不符合固定 schema 或摘要边界。"""


class HarnessSchemaError(HarnessResultError):
    """检测到版本漂移、未知字段或缺少官方结果字段。"""


class HarnessResultFixture(BaseModel):
    """固定 Harness 输出的最小输入模型，不保存原始 patch 或日志。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["swebench-harness-result/v1"]
    instance_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    resolved: bool | None = None
    report: str = Field(default="", max_length=100_000)
    error: str | None = Field(default=None, max_length=1000)
    evaluator_revision: str = Field(min_length=7, max_length=128)
    image_digest: str | None = Field(default=None, min_length=7, max_length=320)


def parse_harness_result(
    payload: Mapping[str, Any] | str | Path,
    *,
    expected_task_id: str | None = None,
    patch_sha256: str | None = None,
) -> HarnessRecheckResult:
    """解析一个 Harness 单题结果并归一为平台无关的 recheck 摘要。"""

    raw = _load_payload(payload)
    _reject_sensitive_keys(raw)
    try:
        fixture = HarnessResultFixture.model_validate(raw)
    except ValidationError as error:
        raise HarnessSchemaError(str(error)) from error
    if expected_task_id is not None and fixture.instance_id != expected_task_id:
        raise HarnessSchemaError(
            f"Harness instance_id mismatch: expected {expected_task_id}, got {fixture.instance_id}"
        )
    status, failure_source = map_harness_status(fixture.status)
    output_digest = _sha256_text(fixture.report)
    reason = fixture.error
    if reason is not None:
        reason, _ = redact_text(reason, max_length=320)
    if status is AdapterStatus.COMPLETED:
        if not isinstance(fixture.resolved, bool):
            return _invalid_recheck(
                fixture,
                patch_sha256=patch_sha256,
                output_digest=output_digest,
                reason="Harness completed result is missing boolean resolved",
            )
        if fixture.image_digest is None:
            return _invalid_recheck(
                fixture,
                patch_sha256=patch_sha256,
                output_digest=output_digest,
                reason="Harness completed result is missing image digest",
            )
        return HarnessRecheckResult(
            task_id=fixture.instance_id,
            status=AdapterStatus.COMPLETED,
            resolved=fixture.resolved,
            patch_sha256=patch_sha256,
            output_digest=output_digest,
            evaluator_revision=fixture.evaluator_revision,
            image_digest=fixture.image_digest,
        )
    if status is AdapterStatus.TIMEOUT:
        return HarnessRecheckResult(
            task_id=fixture.instance_id,
            status=AdapterStatus.TIMEOUT,
            patch_sha256=patch_sha256,
            output_digest=output_digest,
            evaluator_revision=fixture.evaluator_revision,
            image_digest=fixture.image_digest,
            failure_source=failure_source,
            reason=reason or "Harness evaluation timed out",
        )
    if status in {AdapterStatus.FAILED, AdapterStatus.UNAVAILABLE}:
        return HarnessRecheckResult(
            task_id=fixture.instance_id,
            status=status,
            patch_sha256=patch_sha256,
            output_digest=output_digest,
            evaluator_revision=fixture.evaluator_revision,
            image_digest=fixture.image_digest,
            failure_source=failure_source,
            reason=reason or f"Harness status: {fixture.status}",
        )
    return _invalid_recheck(
        fixture,
        patch_sha256=patch_sha256,
        output_digest=output_digest,
        reason=reason or f"Unsupported Harness status: {fixture.status}",
    )


def map_harness_status(
    status: str,
) -> tuple[AdapterStatus, FailureSource | None]:
    """归一化官方 Harness 状态，不把 evaluator 故障当成任务失败。"""

    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"completed", "success", "succeeded", "resolved"}:
        return AdapterStatus.COMPLETED, None
    if normalized in {"timeout", "timed_out"}:
        return AdapterStatus.TIMEOUT, FailureSource.TIMEOUT
    if normalized in {"cancelled", "canceled", "aborted", "interrupted"}:
        return AdapterStatus.FAILED, FailureSource.CANCELLATION
    if normalized in {
        "unavailable",
        "blocked",
        "offline",
        "infra_error",
        "infrastructure_error",
    }:
        return AdapterStatus.UNAVAILABLE, FailureSource.HARNESS
    if normalized in {"error", "failed", "evaluator_error"}:
        return AdapterStatus.FAILED, FailureSource.HARNESS
    return AdapterStatus.INVALID, FailureSource.SCHEMA


def harness_result_to_task_result(
    result: HarnessRecheckResult,
    *,
    manifest: ExperimentManifest,
    attempt: int = 1,
    supports_official_scores: bool = False,
    agent_run: AgentRunSummary | None = None,
) -> TaskResult:
    """把 Harness 结果映射为现有 ``TaskResult``，默认仅产生离线证据。

    ``supports_official_scores`` 是显式的 backend capability。缺省和 fake runner
    都只能得到 blocked/offline_only，避免 fixture 被误报为正式成绩。
    """

    if result.task_id not in manifest.task_ids:
        raise HarnessResultError("Harness task is not selected by manifest")
    if attempt < 1:
        raise HarnessResultError("attempt must be positive")
    if result.status is not AdapterStatus.COMPLETED:
        validity = (
            ResultValidity.BLOCKED
            if result.status in {AdapterStatus.UNAVAILABLE, AdapterStatus.TIMEOUT}
            else ResultValidity.INVALID
        )
        return TaskResult(
            task_id=result.task_id,
            attempt=attempt,
            verdict=(
                TaskVerdict.BLOCKED
                if validity is ResultValidity.BLOCKED
                else TaskVerdict.INVALID
            ),
            validity=validity,
            official=False,
            patch_sha256=result.patch_sha256,
            agent_run=agent_run,
            invalid_reason=result.reason or "Harness result unavailable",
        )

    assert result.resolved is not None
    outcome = VerifierOutcome.PASSED if result.resolved else VerifierOutcome.FAILED
    verifier = VerifierResult(
        outcome=outcome,
        command_summary="official SWE-bench Harness recheck",
        exit_code=0 if result.resolved else 1,
        output_digest=result.output_digest,
    )
    if not supports_official_scores:
        return TaskResult(
            task_id=result.task_id,
            attempt=attempt,
            verdict=TaskVerdict.BLOCKED,
            validity=ResultValidity.OFFLINE_ONLY,
            official=False,
            patch_sha256=result.patch_sha256,
            agent_run=agent_run,
            verifier=verifier,
            invalid_reason="Harness fixture normalized offline; official backend unavailable",
        )
    if result.patch_sha256 is None:
        raise HarnessResultError("Official Harness result requires patch_sha256")
    return TaskResult(
        task_id=result.task_id,
        attempt=attempt,
        verdict=TaskVerdict.PASSED if result.resolved else TaskVerdict.FAILED,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256=result.patch_sha256,
        agent_run=agent_run,
        verifier=verifier,
    )


def _invalid_recheck(
    fixture: HarnessResultFixture,
    *,
    patch_sha256: str | None,
    output_digest: str,
    reason: str,
) -> HarnessRecheckResult:
    return HarnessRecheckResult(
        task_id=fixture.instance_id,
        status=AdapterStatus.INVALID,
        patch_sha256=patch_sha256,
        output_digest=output_digest,
        evaluator_revision=fixture.evaluator_revision,
        image_digest=fixture.image_digest,
        failure_source=FailureSource.SCHEMA,
        reason=reason,
    )


def harness_result_json(result: HarnessRecheckResult) -> str:
    """返回不含 Harness 原始报告的稳定 JSON。"""

    return result.canonical_json() + "\n"


def _load_payload(payload: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    try:
        loaded = json.loads(Path(payload).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HarnessResultError(f"Unable to read Harness result: {payload}") from error
    if not isinstance(loaded, Mapping):
        raise HarnessSchemaError("Harness result must be a JSON object")
    return dict(loaded)


def _reject_sensitive_keys(value: Any) -> None:
    forbidden = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "session",
        "token",
    )
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if any(part in str(key).casefold() for part in forbidden):
                raise HarnessSchemaError("Harness result contains a sensitive field")
            _reject_sensitive_keys(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _reject_sensitive_keys(nested)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__: Sequence[str] = (
    "HARNESS_RESULT_SCHEMA_VERSION",
    "HarnessResultError",
    "HarnessResultFixture",
    "HarnessSchemaError",
    "harness_result_json",
    "harness_result_to_task_result",
    "map_harness_status",
    "parse_harness_result",
)
