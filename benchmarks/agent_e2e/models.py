"""评测协议的严格、版本化数据模型。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "agent-e2e/v1"


class SchemaVersionError(ValueError):
    """读取到当前运行器不支持的评测协议版本时抛出。"""


class VersionedModel(BaseModel):
    """所有持久化评测对象共享的严格 JSON 边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION)
    _expected_schema_version: ClassVar[str] = SCHEMA_VERSION
    _forbidden_extension_key_parts: ClassVar[tuple[str, ...]] = (
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "cookie",
        "password",
        "secret",
        "session",
        "token",
    )

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "VersionedModel":
        if self.schema_version != self._expected_schema_version:
            raise ValueError(
                f"Unsupported schema_version: {self.schema_version}; "
                f"expected {self._expected_schema_version}"
            )
        return self

    @field_validator("extensions", check_fields=False)
    @classmethod
    def _reject_sensitive_extension_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        def check(mapping: Mapping[str, Any]) -> None:
            for key, nested in mapping.items():
                normalized = str(key).casefold()
                if any(part in normalized for part in cls._forbidden_extension_key_parts):
                    raise ValueError("extensions cannot contain credential or session fields")
                if isinstance(nested, Mapping):
                    check(nested)

        check(value)
        return value

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VersionedModel":
        """从外部 JSON 对象读取，先把版本漂移报告为专用错误。"""

        supplied_version = payload.get("schema_version")
        if supplied_version != cls._expected_schema_version:
            raise SchemaVersionError(
                f"Unsupported schema_version: {supplied_version!r}; "
                f"expected {cls._expected_schema_version!r}"
            )
        return cls.model_validate(dict(payload))

    @classmethod
    def from_json(cls, text: str) -> "VersionedModel":
        """从 JSON 文本读取严格版本化模型。"""

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON payload: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("Versioned payload must be a JSON object")
        return cls.from_dict(payload)

    def canonical_json(self) -> str:
        """返回可用于锁定和指纹的稳定 JSON 表示。"""

        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def fingerprint(self) -> str:
        """返回当前严格模型内容的 SHA-256 指纹。"""

        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间，避免本地时区进入 manifest。"""

    return datetime.now(timezone.utc)


class TaskSplit(str, Enum):
    """冻结任务集中的泄漏边界。"""

    REGRESSION = "regression"
    HOLDOUT = "holdout"
    EXTERNAL = "external"


class TaskStatus(str, Enum):
    """任务是否可进入本次评测选择。"""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class TaskVerdict(str, Enum):
    """正式结果的唯一判定集合。"""

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    INVALID = "invalid"


class ResultValidity(str, Enum):
    """区分正式有效、离线证据、阻塞和基础设施无效。"""

    VALID = "valid"
    OFFLINE_ONLY = "offline_only"
    BLOCKED = "blocked"
    INVALID = "invalid"


class WorkerStatus(str, Enum):
    """Agent worker 生命周期在容器边界上的归一化状态。"""

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ERROR = "error"


class VerifierOutcome(str, Enum):
    """后置 verifier 的私有验收结果。"""

    PASSED = "passed"
    FAILED = "failed"


class TaskResources(VersionedModel):
    """公开任务的资源提示，不承载容器挂载或私有资产路径。"""

    cpu_cores: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)
    disk_mb: int | None = Field(default=None, gt=0)
    estimated_minutes: int | None = Field(default=None, gt=0)


class TaskSpec(VersionedModel):
    """Agent 可见任务卡；绝不包含 hidden verifier 或 gold 的实际路径。"""

    task_id: str = Field(min_length=1, max_length=128)
    family: str = Field(min_length=1, max_length=80)
    split: TaskSplit
    repository: str = Field(min_length=1, max_length=240)
    base_revision: str = Field(min_length=7, max_length=128)
    public_prompt: str = Field(min_length=1)
    public_setup: tuple[str, ...] = ()
    public_validation_commands: tuple[str, ...] = ()
    verifier_identity: str = Field(min_length=1, max_length=160)
    gold_evidence_hash: str = Field(min_length=8, max_length=128)
    difficulty: int = Field(ge=1, le=5)
    involved_files: tuple[str, ...] = ()
    resources: TaskResources = Field(default_factory=TaskResources)
    status: TaskStatus = TaskStatus.ACTIVE
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("public_setup", "public_validation_commands", "involved_files")
    @classmethod
    def _reject_blank_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in values):
            raise ValueError("Task tuple fields cannot contain blank items")
        return values


class Catalog(VersionedModel):
    """可提交的公开 catalog；私有验收资产属于 host registry。"""

    catalog_id: str = Field(min_length=1, max_length=128)
    catalog_version: str = Field(min_length=1, max_length=64)
    tasks: tuple[TaskSpec, ...] = Field(min_length=1)
    extensions: dict[str, Any] = Field(default_factory=dict)


class CatalogLock(VersionedModel):
    """运行前冻结 catalog 内容与任务选择的锁文件。"""

    catalog_id: str = Field(min_length=1, max_length=128)
    catalog_version: str = Field(min_length=1, max_length=64)
    catalog_sha256: str = Field(min_length=64, max_length=64)
    task_ids: tuple[str, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_unique_task_ids(self) -> "CatalogLock":
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Catalog lock task_ids must be unique")
        return self


class ExperimentProfile(VersionedModel):
    """可审计但不保存凭证值的 Agent 配置快照。"""

    profile_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=128)
    thinking_level: str = Field(default="off", min_length=1, max_length=32)
    permission_mode: str = Field(default="bypassPermissions", min_length=1, max_length=64)
    prompt_version: str = Field(min_length=1, max_length=128)
    compression_version: str = Field(min_length=1, max_length=128)
    tool_policy_version: str = Field(min_length=1, max_length=128)
    seed: int
    repeats: int = Field(ge=1, le=100)
    timeout_seconds: float = Field(gt=0)
    budget_usd: float = Field(ge=0)
    max_turns: int | None = Field(default=None, gt=0)
    agent_code_sha: str = Field(min_length=7, max_length=128)
    credential_env_vars: tuple[str, ...] = ()
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("credential_env_vars")
    @classmethod
    def _validate_env_var_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not value or not value.replace("_", "").isalnum() or value[0].isdigit():
                raise ValueError("credential_env_vars must contain environment variable names")
        return values

    def require_online_budget(self) -> None:
        """在线执行前确认调用方显式提供了正预算与凭证变量名。"""

        if self.budget_usd <= 0:
            raise ValueError("Online execution requires a positive budget_usd")
        if not self.credential_env_vars:
            raise ValueError("Online execution requires credential_env_vars names")


class ExperimentManifest(VersionedModel):
    """不可变实验输入；profile/catalog 均以内嵌冻结快照保存。"""

    run_id: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    agent_code_sha: str = Field(min_length=7, max_length=128)
    evaluator_code_sha: str = Field(min_length=7, max_length=128)
    catalog: CatalogLock
    profile: ExperimentProfile
    profile_fingerprint: str = Field(min_length=64, max_length=64)
    task_ids: tuple[str, ...] = Field(min_length=1)
    seed: int
    repeats: int = Field(ge=1, le=100)
    timeout_seconds: float = Field(gt=0)
    budget_usd: float = Field(ge=0)
    platform: str = Field(min_length=1, max_length=128)
    agent_image_digest: str | None = Field(default=None, min_length=7, max_length=256)
    verifier_image_digest: str | None = Field(default=None, min_length=7, max_length=256)
    resume_from_run_id: str | None = Field(default=None, min_length=1, max_length=128)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_frozen_inputs(self) -> "ExperimentManifest":
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Manifest task_ids must be unique")
        if not set(self.task_ids).issubset(self.catalog.task_ids):
            raise ValueError("Manifest task_ids must be selected from its catalog lock")
        if self.profile_fingerprint != self.profile.fingerprint():
            raise ValueError("Manifest profile_fingerprint does not match profile")
        if self.agent_code_sha != self.profile.agent_code_sha:
            raise ValueError("Manifest and profile agent_code_sha must match")
        if self.seed != self.profile.seed:
            raise ValueError("Manifest and profile seed must match")
        if self.repeats != self.profile.repeats:
            raise ValueError("Manifest and profile repeats must match")
        if self.timeout_seconds != self.profile.timeout_seconds:
            raise ValueError("Manifest and profile timeout_seconds must match")
        if self.budget_usd != self.profile.budget_usd:
            raise ValueError("Manifest and profile budget_usd must match")
        return self


class AgentRunSummary(VersionedModel):
    """从 Agent.run 提炼的无 session-ID、无原始文本的受控结果。"""

    final_text_digest: str = Field(min_length=64, max_length=64)
    final_text_preview: str = Field(default="", max_length=320)
    stop_reason: str = Field(min_length=1, max_length=128)
    turns: int = Field(ge=0)
    wall_time_seconds: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    error_summary: str | None = Field(default=None, max_length=320)


class TraceSummary(VersionedModel):
    """受控轨迹的可序列化摘要；不保存用户 session 或完整工具输出。"""

    trace_id: str = Field(min_length=1, max_length=128)
    event_count: int = Field(ge=0)
    event_types: tuple[str, ...] = ()
    redaction_count: int = Field(ge=0)
    loop_fingerprints: tuple[str, ...] = ()
    trace_digest: str = Field(min_length=64, max_length=64)


class WorkerResult(VersionedModel):
    """Agent 容器返回给 host 的最小、无密钥 worker 结果。"""

    status: WorkerStatus
    agent_run: AgentRunSummary | None = None
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    patch_applied: bool | None = None
    trace_summary: TraceSummary | None = None
    error_summary: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _validate_worker_status(self) -> "WorkerResult":
        if self.status is WorkerStatus.COMPLETED and self.agent_run is None:
            raise ValueError("Completed worker results require agent_run")
        if self.status is not WorkerStatus.COMPLETED and not self.error_summary:
            raise ValueError("Timeout/error worker results require error_summary")
        return self


class VerifierResult(VersionedModel):
    """后置 verifier 对 patch 的归一化私有验收输出。"""

    outcome: VerifierOutcome
    command_summary: str = Field(min_length=1, max_length=320)
    exit_code: int
    output_digest: str = Field(min_length=64, max_length=64)
    output_preview: str = Field(default="", max_length=320)


class TaskResult(VersionedModel):
    """单次任务结果；passed/failed 只能来自真实隔离 verifier。"""

    task_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1)
    verdict: TaskVerdict
    validity: ResultValidity
    official: bool = False
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    patch_applied: bool | None = None
    agent_run: AgentRunSummary | None = None
    trace_summary: TraceSummary | None = None
    verifier: VerifierResult | None = None
    cost_usd: float = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    invalid_reason: str | None = Field(default=None, max_length=320)
    resumed_from_checkpoint: bool = False
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _enforce_official_isolation(self) -> "TaskResult":
        if self.verdict in {TaskVerdict.PASSED, TaskVerdict.FAILED}:
            if not self.official or self.validity is not ResultValidity.VALID:
                raise ValueError("passed/failed require an official valid result")
            if self.verifier is None:
                raise ValueError("passed/failed require a verifier result")
            if self.patch_sha256 is None:
                raise ValueError("passed/failed require a patch_sha256")
            expected_outcome = (
                VerifierOutcome.PASSED
                if self.verdict is TaskVerdict.PASSED
                else VerifierOutcome.FAILED
            )
            if self.verifier.outcome is not expected_outcome:
                raise ValueError("Official verdict must match verifier outcome")
        if self.verdict is TaskVerdict.BLOCKED:
            if self.official or self.validity not in {
                ResultValidity.BLOCKED,
                ResultValidity.OFFLINE_ONLY,
            }:
                raise ValueError("blocked results cannot be official")
        if self.verdict is TaskVerdict.INVALID:
            if self.official or self.validity is not ResultValidity.INVALID:
                raise ValueError("invalid results cannot be official")
            if not self.invalid_reason:
                raise ValueError("invalid results require invalid_reason")
        return self


class FailureMode(str, Enum):
    """为后续失败回流保留的稳定分类词汇。"""

    LOOP = "loop"
    CONTEXT_DECAY = "context_decay"
    TOOL_MISUSE = "tool_misuse"
    PREMATURE_TERMINATION = "premature_termination"
    INFRASTRUCTURE = "infrastructure"
    UNCLASSIFIED = "unclassified"


class FailureRecord(VersionedModel):
    """失败回流子任务可复用的严格证据索引，暂不执行自动归因。"""

    task_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1)
    primary_mode: FailureMode
    secondary_modes: tuple[FailureMode, ...] = ()
    evidence_offsets: tuple[int, ...] = ()
    failure_signature: str = Field(min_length=64, max_length=64)
    reproduction_command: str = Field(min_length=1, max_length=320)
    triage_owner: str | None = Field(default=None, max_length=128)
    deduplicated: bool = False
    feedback_split: TaskSplit | None = None
    holdout_exclusion_reason: str | None = Field(default=None, max_length=320)
    extensions: dict[str, Any] = Field(default_factory=dict)


class GateStatus(str, Enum):
    """为后续 gate 子任务预留的可序列化状态。"""

    PASS = "pass"
    REJECT = "reject"
    INVALID = "invalid"
    WAIVED = "waived"


class GateResult(VersionedModel):
    """报告可保留 gate 的已知状态与显式扩展，而不接受未知顶层字段。"""

    status: GateStatus
    reason: str = Field(min_length=1, max_length=320)
    baseline_run_id: str = Field(min_length=1, max_length=128)
    candidate_run_id: str = Field(min_length=1, max_length=128)
    extensions: dict[str, Any] = Field(default_factory=dict)


class ReportStatus(str, Enum):
    """报告是否包含正式隔离得分。"""

    BLOCKED = "blocked"
    OFFLINE = "offline"
    OFFICIAL = "official"


class OfficialScore(VersionedModel):
    """只在真实隔离 verifier 完整运行后存在的正式汇总。"""

    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    valid_denominator: int = Field(ge=1)
    success_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_counts(self) -> "OfficialScore":
        if self.passed_count + self.failed_count != self.valid_denominator:
            raise ValueError("Official score counts must equal valid denominator")
        if self.success_rate != self.passed_count / self.valid_denominator:
            raise ValueError("Official score success_rate must match counts")
        return self


class EvaluationReport(VersionedModel):
    """JSON/中文报告的严格根对象；离线报告刻意没有正式分数。"""

    manifest: ExperimentManifest
    results: tuple[TaskResult, ...]
    status: ReportStatus
    official_score: OfficialScore | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_report_scope(self) -> "EvaluationReport":
        result_ids = {result.task_id for result in self.results}
        if not result_ids.issubset(set(self.manifest.task_ids)):
            raise ValueError("Report includes a task outside its manifest")
        official_results = [result for result in self.results if result.official]
        if official_results and self.official_score is None:
            raise ValueError("Official results require an official_score")
        if not official_results and self.official_score is not None:
            raise ValueError("Offline/blocked reports cannot contain official_score")
        if self.status is ReportStatus.OFFICIAL and not official_results:
            raise ValueError("Official report status requires official results")
        if self.status is not ReportStatus.OFFICIAL and official_results:
            raise ValueError("Only official reports may contain official results")
        if self.official_score is not None:
            passed_count = sum(
                result.verdict is TaskVerdict.PASSED for result in official_results
            )
            failed_count = sum(
                result.verdict is TaskVerdict.FAILED for result in official_results
            )
            if (
                self.official_score.passed_count != passed_count
                or self.official_score.failed_count != failed_count
                or self.official_score.valid_denominator != len(official_results)
            ):
                raise ValueError("Official score does not match official task results")
        return self
