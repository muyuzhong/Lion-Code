"""SWE-bench Verified 的平台无关适配契约。

阶段一只解析 Harbor fixture、归一化 routine verifier 状态并生成受控摘要；这里
不启动 Harbor/Docker，也不声称产生正式 SWE-bench 分数。真实 installed-agent
runner 留给 Linux 阶段。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .models import (
    AdapterStatus,
    FailureSource,
    HarborRoutineVerifierResult,
    TrialExecutionStatus,
    VerifierOutcome,
)
from .trace import redact_text

HARBOR_RESULT_SCHEMA_VERSION = "harbor-result/v1"


class HarborResultError(ValueError):
    """Harbor result fixture 不满足固定版本或安全边界。"""


class HarborPathBoundaryError(HarborResultError):
    """Harbor artifact path 越出了 host 控制的 job root。"""


class HarborSchemaError(HarborResultError):
    """Harbor schema 漂移或未知字段。"""


class HarborResultFixture(BaseModel):
    """仅用于读取固定 Harbor fixture 的严格输入模型。

    该 raw schema 不会直接持久化；归一化后的结果使用 ``agent-e2e/v1``。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["harbor-result/v1"]
    task_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=240)
    status: str = Field(min_length=1, max_length=80)
    reward: float | None = Field(default=None, ge=0, le=1)
    verifier_outcome: VerifierOutcome | None = None
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    patch_path: str | None = Field(default=None, min_length=1, max_length=1000)
    artifact_paths: tuple[str, ...] = Field(default=(), max_length=256)
    output: str = Field(default="", max_length=100_000)
    command_summary: str | None = Field(default=None, max_length=1000)
    wall_time_seconds: float | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=1000)
    failure_source: str | None = Field(default=None, max_length=80)

    @field_validator("artifact_paths")
    @classmethod
    def _validate_artifact_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 1000 for value in values):
            raise ValueError("Harbor artifact paths must be bounded and non-empty")
        return values


def parse_harbor_result(
    payload: Mapping[str, Any] | str | Path,
    *,
    job_root: str | Path | None = None,
    expected_task_id: str | None = None,
) -> HarborRoutineVerifierResult:
    """解析固定 Harbor result 并只保留 reward、digest 和受控状态。

    ``job_root`` 存在时，patch/artifact 路径必须位于其内部；返回值只记录相对
    引用，不会将宿主绝对路径写入结果。输入中的 secret key 会被拒绝，而 output
    正文只用于计算 digest 和短脱敏预览。
    """

    raw = _load_payload(payload)
    _reject_sensitive_keys(raw)
    try:
        fixture = HarborResultFixture.model_validate(raw)
    except ValidationError as error:
        raise HarborSchemaError(str(error)) from error
    if expected_task_id is not None and fixture.task_id != expected_task_id:
        raise HarborSchemaError(
            f"Harbor task_id mismatch: expected {expected_task_id}, got {fixture.task_id}"
        )

    root = Path(job_root).resolve() if job_root is not None else None
    if root is None and (fixture.patch_path is not None or fixture.artifact_paths):
        raise HarborPathBoundaryError(
            "job_root is required when Harbor result references artifacts"
        )
    artifact_references: list[str] = []
    for value in fixture.artifact_paths:
        artifact_references.append(_safe_artifact_reference(value, root))
    patch_sha256 = fixture.patch_sha256
    if fixture.patch_path is not None:
        patch_path = _safe_artifact_path(fixture.patch_path, root)
        if not patch_path.is_file():
            raise HarborResultError(
                f"Harbor patch artifact does not exist: {fixture.patch_path}"
            )
        observed = _sha256_file(patch_path)
        if patch_sha256 is not None and observed != patch_sha256:
            raise HarborResultError("Harbor patch digest does not match patch artifact")
        patch_sha256 = observed
        artifact_references.append(_safe_artifact_reference(fixture.patch_path, root))

    status, execution_status, source = map_harbor_status(
        fixture.status,
        failure_source=fixture.failure_source,
    )
    reason = fixture.error
    if reason is not None:
        reason, _ = _redact_controlled_text(reason, job_root=root, max_length=320)
        reason = reason or None
    output_digest = _sha256_text(fixture.output) if fixture.output else None
    command_summary = None
    if fixture.command_summary is not None:
        command_summary, _ = _redact_controlled_text(
            fixture.command_summary,
            job_root=root,
            max_length=320,
        )
    if status is not AdapterStatus.COMPLETED and not reason:
        reason = f"Harbor status: {fixture.status}"
    if status is AdapterStatus.COMPLETED and (
        fixture.reward is None or fixture.verifier_outcome is None
    ):
        status = AdapterStatus.INVALID
        execution_status = TrialExecutionStatus.INFRA_FAILED
        source = FailureSource.SCHEMA
        reason = "Harbor completed result is missing reward or verifier outcome"
    return HarborRoutineVerifierResult(
        task_id=fixture.task_id,
        job_id=fixture.job_id,
        status=status,
        execution_status=execution_status,
        verifier_outcome=fixture.verifier_outcome,
        reward=fixture.reward,
        patch_sha256=patch_sha256,
        patch_applied=patch_sha256 is not None,
        output_digest=output_digest,
        command_summary=command_summary,
        artifact_references=tuple(artifact_references),
        failure_source=source,
        reason=reason,
        wall_time_seconds=fixture.wall_time_seconds,
    )


def map_harbor_status(
    status: str,
    *,
    failure_source: str | None = None,
) -> tuple[AdapterStatus, TrialExecutionStatus, FailureSource | None]:
    """将 Harbor/agent 状态映射为与 verifier 得分正交的生命周期事实。"""

    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    source = _failure_source(failure_source)
    if normalized in {"completed", "success", "succeeded", "passed", "resolved"}:
        return AdapterStatus.COMPLETED, TrialExecutionStatus.COMPLETED, None
    if normalized in {
        "agent_error",
        "error",
        "failed",
        "agent_failed",
        "budget_exhausted",
    }:
        return (
            AdapterStatus.FAILED,
            TrialExecutionStatus.SUBJECT_FAILED,
            source or FailureSource.HARBOR,
        )
    if normalized in {"timeout", "timed_out"}:
        return (
            AdapterStatus.TIMEOUT,
            TrialExecutionStatus.SUBJECT_FAILED,
            source or FailureSource.TIMEOUT,
        )
    if normalized in {"cancelled", "canceled", "aborted", "interrupted"}:
        return (
            AdapterStatus.FAILED,
            TrialExecutionStatus.INDETERMINATE,
            source or FailureSource.CANCELLATION,
        )
    if normalized in {"docker_error", "image_error"}:
        return (
            AdapterStatus.UNAVAILABLE,
            TrialExecutionStatus.INFRA_FAILED,
            source or FailureSource.DOCKER,
        )
    if normalized in {
        "infra_error",
        "infrastructure_error",
        "communication_error",
        "unavailable",
        "blocked",
    }:
        return (
            AdapterStatus.UNAVAILABLE,
            TrialExecutionStatus.INFRA_FAILED,
            source or FailureSource.HARBOR,
        )
    if normalized in {"path_error", "artifact_path_error"}:
        return (
            AdapterStatus.INVALID,
            TrialExecutionStatus.INFRA_FAILED,
            source or FailureSource.PATH,
        )
    if normalized in {"cleanup_error", "cleanup_failed"}:
        return (
            AdapterStatus.FAILED,
            TrialExecutionStatus.INDETERMINATE,
            source or FailureSource.CLEANUP,
        )
    return (
        AdapterStatus.INVALID,
        TrialExecutionStatus.INFRA_FAILED,
        source or FailureSource.SCHEMA,
    )


def harbor_result_json(result: HarborRoutineVerifierResult) -> str:
    """返回仅含 agent-e2e/v1 字段的稳定 JSON。"""

    return result.canonical_json() + "\n"


def _load_payload(payload: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    try:
        text = Path(payload).read_text(encoding="utf-8")
        loaded = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HarborResultError(f"Unable to read Harbor result: {payload}") from error
    if not isinstance(loaded, Mapping):
        raise HarborSchemaError("Harbor result must be a JSON object")
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
                raise HarborSchemaError("Harbor result contains a sensitive field")
            _reject_sensitive_keys(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _reject_sensitive_keys(nested)


def _safe_artifact_path(value: str, root: Path | None) -> Path:
    try:
        raw_path = Path(value)
        if root is None:
            if not raw_path.is_absolute():
                raise HarborPathBoundaryError(
                    "relative artifact paths require job_root"
                )
            return raw_path.resolve()
        candidate = (
            (root / value).resolve()
            if not raw_path.is_absolute()
            else raw_path.resolve()
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise HarborPathBoundaryError("Harbor artifact path is invalid") from error
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise HarborPathBoundaryError(
            "Harbor artifact path escapes job_root"
        ) from error
    return candidate


def _safe_artifact_reference(value: str, root: Path | None) -> str:
    candidate = _safe_artifact_path(value, root)
    if root is None:
        return candidate.name
    if candidate == root:
        raise HarborPathBoundaryError("Harbor artifact path must name a child path")
    return candidate.relative_to(root).as_posix()


def _failure_source(value: str | None) -> FailureSource | None:
    if value is None:
        return None
    try:
        return FailureSource(value.casefold())
    except ValueError:
        return FailureSource.SCHEMA


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_controlled_text(
    value: str,
    *,
    job_root: Path | None,
    max_length: int,
) -> tuple[str, int]:
    if job_root is not None:
        for representation in {str(job_root), job_root.as_posix()}:
            value = value.replace(representation, "<job_root>")
    return redact_text(value, max_length=max_length)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__: Sequence[str] = (
    "HARBOR_RESULT_SCHEMA_VERSION",
    "HarborPathBoundaryError",
    "HarborResultError",
    "HarborResultFixture",
    "HarborRoutineVerifierResult",
    "HarborSchemaError",
    "harbor_result_json",
    "map_harbor_status",
    "parse_harbor_result",
)
