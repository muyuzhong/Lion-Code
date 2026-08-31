"""评测协议的严格、版本化数据模型。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

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
    def _validate_schema_version(self) -> Self:
        if self.schema_version != self._expected_schema_version:
            raise ValueError(
                f"Unsupported schema_version: {self.schema_version}; "
                f"expected {self._expected_schema_version}"
            )
        return self

    @field_validator("extensions", check_fields=False)
    @classmethod
    def _reject_sensitive_extension_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        def check(value: Any) -> None:
            if isinstance(value, Mapping):
                items = value.items()
            elif isinstance(value, (list, tuple, set, frozenset)):
                for nested in value:
                    check(nested)
                return
            else:
                return
            for key, nested in items:
                normalized = str(key).casefold()
                if any(
                    part in normalized for part in cls._forbidden_extension_key_parts
                ):
                    raise ValueError(
                        "extensions cannot contain credential or session fields"
                    )
                check(nested)

        check(value)
        return value

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        """从外部 JSON 对象读取，先把版本漂移报告为专用错误。"""

        supplied_version = payload.get("schema_version")
        if supplied_version != cls._expected_schema_version:
            raise SchemaVersionError(
                f"Unsupported schema_version: {supplied_version!r}; "
                f"expected {cls._expected_schema_version!r}"
            )
        return cls.model_validate(dict(payload))

    @classmethod
    def from_json(cls, text: str) -> Self:
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

    return datetime.now(UTC)


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


class TrialExecutionStatus(str, Enum):
    """一次 Verified trial 的生命周期状态，与任务得分保持正交。"""

    COMPLETED = "completed"
    SUBJECT_FAILED = "subject_failed"
    INFRA_FAILED = "infra_failed"
    INDETERMINATE = "indeterminate"


class AdapterStatus(str, Enum):
    """外部适配器的结果状态；不可用不等于被测 Agent 失败。"""

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    INVALID = "invalid"
    FAILED = "failed"
    TIMEOUT = "timeout"


class FailureSource(str, Enum):
    """平台适配器故障来源，和 ``TrialExecutionStatus`` 分开记录。"""

    HARBOR = "harbor"
    HARNESS = "harness"
    DEEPEVAL = "deepeval"
    OPIK = "opik"
    DOCKER = "docker"
    SCHEMA = "schema"
    PATH = "path"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    CLEANUP = "cleanup"


class DeepEvalAnalysisStatus(str, Enum):
    """DeepEval 过程分析状态；不改变确定性 verifier 结论。"""

    COMPLETED = "completed"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMEOUT = "timeout"


class OpikExportStatus(str, Enum):
    """Opik 后置可观测性发布状态。"""

    EXPORTED = "exported"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMEOUT = "timeout"


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
    def _validate_unique_task_ids(self) -> CatalogLock:
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Catalog lock task_ids must be unique")
        return self


class ExperimentProfile(VersionedModel):
    """可审计但不保存凭证值的 Agent 配置快照。"""

    profile_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=128)
    thinking_level: str = Field(default="off", min_length=1, max_length=32)
    permission_mode: str = Field(
        default="bypassPermissions", min_length=1, max_length=64
    )
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
                raise ValueError(
                    "credential_env_vars must contain environment variable names"
                )
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
    verifier_image_digest: str | None = Field(
        default=None, min_length=7, max_length=256
    )
    resume_from_run_id: str | None = Field(default=None, min_length=1, max_length=128)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_frozen_inputs(self) -> ExperimentManifest:
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


class VerifiedProvenance(VersionedModel):
    """从已提交 Git object 构建的 Verified 产物 provenance。

    这里只保留可复核的摘要和版本指纹；源 checkout、临时目录和凭证不属于
    持久化契约。``dirty_worktree`` 固定为 false，避免调用方误把工作区文件
    当成评测对象。
    """

    git_commit_sha: str = Field(min_length=7, max_length=128)
    git_tree_sha: str = Field(min_length=7, max_length=128)
    wheel_sha256: str = Field(min_length=64, max_length=64)
    wheel_filename: str = Field(min_length=1, max_length=240)
    wheel_size_bytes: int = Field(ge=1)
    source_tree_sha256: str = Field(min_length=64, max_length=64)
    repository_fingerprint: str = Field(min_length=64, max_length=64)
    python_version: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=128)
    builder_version: str = Field(min_length=1, max_length=128)
    dirty_worktree: Literal[False] = False
    source_kind: Literal["git_object"] = "git_object"
    harbor_version: str | None = Field(default=None, max_length=128)
    swebench_version: str | None = Field(default=None, max_length=128)
    deepeval_version: str | None = Field(default=None, max_length=128)
    opik_version: str | None = Field(default=None, max_length=128)
    image_digest: str | None = Field(default=None, max_length=320)
    network_policy_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    dependency_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("wheel_filename")
    @classmethod
    def _validate_wheel_filename(cls, value: str) -> str:
        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("wheel_filename must be a plain file name")
        if not value.endswith(".whl"):
            raise ValueError("wheel_filename must end with .whl")
        return value

    @field_validator(
        "git_commit_sha",
        "git_tree_sha",
        "wheel_sha256",
        "source_tree_sha256",
        "repository_fingerprint",
        "network_policy_fingerprint",
        "dependency_fingerprint",
    )
    @classmethod
    def _validate_hex_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(character not in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("provenance digests must be hexadecimal")
        return value.lower()


class TrialExecution(VersionedModel):
    """Harbor trial 生命周期摘要，不承担任务正确性判定。"""

    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=160)
    attempt: int = Field(ge=1)
    status: TrialExecutionStatus
    failure_source: FailureSource | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    wall_time_seconds: float = Field(ge=0)
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    trace_digest: str | None = Field(default=None, min_length=64, max_length=64)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_failure_state(self) -> TrialExecution:
        if self.finished_at < self.started_at:
            raise ValueError("trial finished_at cannot precede started_at")
        failed = self.status is not TrialExecutionStatus.COMPLETED
        if failed and self.reason is None:
            raise ValueError("non-completed trials require a controlled reason")
        if (
            self.status is TrialExecutionStatus.COMPLETED
            and self.failure_source is not None
        ):
            raise ValueError("completed trials cannot carry a failure source")
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


class DeepEvalTrajectoryEvent(VersionedModel):
    """供离线 Judge/Opik 共用的单个脱敏事件，只携带摘要和 digest。"""

    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=160)
    payload_digest: str = Field(min_length=64, max_length=64)
    tool_name: str | None = Field(default=None, max_length=160)
    argument_digest: str | None = Field(default=None, min_length=64, max_length=64)
    workspace_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=128
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DeepEvalTrajectory(VersionedModel):
    """同一条 Lion typed trace 的有界、可脱敏投影。"""

    task_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=128)
    trace_digest: str = Field(min_length=64, max_length=64)
    events: tuple[DeepEvalTrajectoryEvent, ...] = Field(max_length=256)
    deterministic_verdict: TaskVerdict | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class DeepEvalCase(VersionedModel):
    """传给 DeepEval SDK 的最小 case；不含 prompt、推理或工具正文。

    ``input_preview``/``outcome_preview`` 只携带脱敏截断后的受控摘要
    （任务卡公开文本与最终结果预览），供 judge 恢复任务的真实意图；
    工具参数、中间输出与原始正文一律不进入 case。
    """

    task_id: str = Field(min_length=1, max_length=160)
    input_digest: str = Field(min_length=64, max_length=64)
    trajectory: DeepEvalTrajectory
    expected_verdict: TaskVerdict | None = None
    input_preview: str | None = Field(default=None, max_length=4000)
    outcome_preview: str | None = Field(default=None, max_length=2000)
    extensions: dict[str, Any] = Field(default_factory=dict)


class RequestedVariant(VersionedModel):
    """profile 声明的 Harness 变量版本(注入前的事实)。"""

    prompt_version: str | None = None
    tool_policy_version: str | None = None
    compression_version: str | None = None


class ResolvedVariant(VersionedModel):
    """注入解析命中的事实:哪些声明版本真的映射到了运行配置。"""

    prompt_hit: bool = False
    tool_policy_hit: bool = False


class InjectionEvidence(VersionedModel):
    """一次执行的注入证据;fingerprint 非空 = 真的注入了。

    ``prompt_sha256`` / ``tool_policy_sha256`` 是各维度注入内容的摘要,
    供 run 级校验按声明维度精确核对(而不只看复合指纹)。
    """

    requested: RequestedVariant = Field(default_factory=RequestedVariant)
    resolved_variant: ResolvedVariant = Field(default_factory=ResolvedVariant)
    injection_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    prompt_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    tool_policy_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    extensions: dict[str, Any] = Field(default_factory=dict)


class RunInjectionEvidence(VersionedModel):
    """一次 run(全部 task×attempt)的注入证据聚合。

    只有整个 run 的 requested / resolved / fingerprint 完全一致时才存在,
    用来证明「这条 run 的每一次执行都经历了同一个 treatment」;任一
    结果缺失或不一致,整个 run 视为没有可用的注入证据。
    """

    requested: RequestedVariant = Field(default_factory=RequestedVariant)
    resolved_variant: ResolvedVariant = Field(default_factory=ResolvedVariant)
    injection_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    prompt_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    tool_policy_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    result_count: int = Field(ge=1)
    extensions: dict[str, Any] = Field(default_factory=dict)


class WorkerResult(VersionedModel):
    """Agent 容器返回给 host 的最小、无密钥 worker 结果。"""

    status: WorkerStatus
    agent_run: AgentRunSummary | None = None
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    patch_applied: bool | None = None
    trace_summary: TraceSummary | None = None
    error_summary: str | None = Field(default=None, max_length=320)
    injection_evidence: InjectionEvidence | None = None

    @model_validator(mode="after")
    def _validate_worker_status(self) -> WorkerResult:
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


class HarborRoutineVerifierResult(VersionedModel):
    """Harbor 日常 verifier 的受控结果；它永远不是 official score。"""

    task_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=240)
    status: AdapterStatus
    execution_status: TrialExecutionStatus
    verifier_outcome: VerifierOutcome | None = None
    reward: float | None = Field(default=None, ge=0, le=1)
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    patch_applied: bool | None = None
    output_digest: str | None = Field(default=None, min_length=64, max_length=64)
    command_summary: str | None = Field(default=None, max_length=320)
    artifact_references: tuple[str, ...] = Field(default=(), max_length=256)
    failure_source: FailureSource | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    wall_time_seconds: float | None = Field(default=None, ge=0)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_status(self) -> HarborRoutineVerifierResult:
        if self.status is AdapterStatus.COMPLETED:
            if self.verifier_outcome is None or self.reward is None:
                raise ValueError("completed Harbor results require reward and outcome")
            if self.execution_status not in {
                TrialExecutionStatus.COMPLETED,
                TrialExecutionStatus.SUBJECT_FAILED,
            }:
                raise ValueError("completed Harbor results require a finished trial")
            if self.failure_source is not None:
                raise ValueError(
                    "completed Harbor results cannot carry a failure source"
                )
        elif self.reason is None:
            raise ValueError("non-completed Harbor results require a reason")
        elif self.failure_source is None:
            raise ValueError("non-completed Harbor results require a failure source")
        if self.patch_applied is True and self.patch_sha256 is None:
            raise ValueError("patch_applied requires patch_sha256")
        if self.patch_applied is False and self.patch_sha256 is not None:
            raise ValueError("patch_sha256 requires patch_applied")
        return self

    @field_validator("artifact_references")
    @classmethod
    def _validate_artifact_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            path = Path(value)
            if (
                not value.strip()
                or "\\" in value
                or path.is_absolute()
                or path == Path(".")
                or ".." in path.parts
                or len(value) > 1000
            ):
                raise ValueError("artifact_references must be relative POSIX paths")
        return values


class HarnessRecheckResult(VersionedModel):
    """官方 SWE-bench Harness 复核摘要，原始 patch/log 不进入模型。"""

    task_id: str = Field(min_length=1, max_length=160)
    status: AdapterStatus
    resolved: bool | None = None
    patch_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    output_digest: str = Field(min_length=64, max_length=64)
    evaluator_revision: str = Field(min_length=7, max_length=128)
    image_digest: str | None = Field(default=None, min_length=7, max_length=320)
    failure_source: FailureSource | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_result(self) -> HarnessRecheckResult:
        if self.status is AdapterStatus.COMPLETED and self.resolved is None:
            raise ValueError("completed Harness results require boolean resolved")
        if self.status is not AdapterStatus.COMPLETED and self.reason is None:
            raise ValueError("non-completed Harness results require a reason")
        if self.status is AdapterStatus.COMPLETED and self.image_digest is None:
            raise ValueError("completed Harness results require an image digest")
        if self.status is AdapterStatus.COMPLETED and self.failure_source is not None:
            raise ValueError("completed Harness results cannot carry a failure source")
        if self.status is not AdapterStatus.COMPLETED and self.failure_source is None:
            raise ValueError("non-completed Harness results require a failure source")
        if self.status is not AdapterStatus.COMPLETED and self.resolved is not None:
            raise ValueError("non-completed Harness results cannot claim resolved")
        return self


class DeepEvalMetricResult(VersionedModel):
    """单项 DeepEval Judge 评分；reason 仅为受控短摘要。"""

    name: str = Field(min_length=1, max_length=160)
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    model: str = Field(min_length=1, max_length=256)
    input_digest: str = Field(min_length=64, max_length=64)
    status: AdapterStatus = AdapterStatus.COMPLETED
    threshold: float | None = Field(default=None, ge=0, le=1)
    threshold_met: bool | None = None
    samples: int = Field(default=1, ge=1)
    score_min: float | None = Field(default=None, ge=0, le=1)
    score_max: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_score(self) -> DeepEvalMetricResult:
        if self.status is AdapterStatus.COMPLETED and self.score is None:
            raise ValueError("completed DeepEval metric requires a score")
        if self.status is not AdapterStatus.COMPLETED and self.reason is None:
            raise ValueError("failed DeepEval metric requires a reason")
        if self.status is not AdapterStatus.COMPLETED and self.score is not None:
            raise ValueError("failed DeepEval metrics cannot carry a score")
        if (self.threshold is None) != (self.threshold_met is None):
            raise ValueError(
                "DeepEval metric threshold and threshold_met must be both set or both unset"
            )
        if self.threshold is not None:
            expected = (
                self.status is AdapterStatus.COMPLETED
                and self.score is not None
                and float(self.score) >= float(self.threshold)
            )
            if self.threshold_met != expected:
                raise ValueError(
                    "DeepEval metric threshold_met must match score vs threshold"
                )
        if (self.score_min is None) != (self.score_max is None):
            raise ValueError(
                "DeepEval metric score_min and score_max must be both set or both unset"
            )
        if self.status is AdapterStatus.COMPLETED:
            if self.samples > 1 and (self.score_min is None or self.score_max is None):
                raise ValueError(
                    "multi-sample DeepEval metrics require score_min and score_max"
                )
            if self.score_min is not None:
                # 均值聚合允许浮点舍入容差。
                if not (self.score_min - 1e-9 <= self.score <= self.score_max + 1e-9):
                    raise ValueError(
                        "DeepEval metric score must lie in [score_min, score_max]"
                    )
        elif self.score_min is not None:
            raise ValueError("failed DeepEval metrics cannot carry a score range")
        return self


class DeepEvalAnalysis(VersionedModel):
    """运行后离线分析；它没有权限覆盖 Harness/TaskResult。"""

    task_id: str = Field(min_length=1, max_length=160)
    status: DeepEvalAnalysisStatus
    judge_model: str = Field(min_length=1, max_length=256)
    input_digest: str = Field(min_length=64, max_length=64)
    trajectory_digest: str = Field(min_length=64, max_length=64)
    metrics: tuple[DeepEvalMetricResult, ...] = Field(default=(), max_length=64)
    agent_model: str | None = Field(default=None, max_length=256)
    judge_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    failure_source: FailureSource | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_analysis(self) -> DeepEvalAnalysis:
        if self.status is DeepEvalAnalysisStatus.COMPLETED and not self.metrics:
            raise ValueError("completed DeepEval analysis requires metrics")
        if self.status is not DeepEvalAnalysisStatus.COMPLETED and self.reason is None:
            raise ValueError("unavailable DeepEval analysis requires a reason")
        if (
            self.status is DeepEvalAnalysisStatus.COMPLETED
            and self.failure_source is not None
        ):
            raise ValueError(
                "completed DeepEval analysis cannot carry a failure source"
            )
        if (
            self.status is not DeepEvalAnalysisStatus.COMPLETED
            and self.failure_source is None
        ):
            raise ValueError(
                "non-completed DeepEval analysis requires a failure source"
            )
        metric_names = [metric.name for metric in self.metrics]
        if len(set(metric_names)) != len(metric_names):
            raise ValueError("DeepEval metric names must be unique")
        return self


class OpikSpan(VersionedModel):
    """Opik trace 中的受控 span；只保存 digest，不保存原始输入输出。"""

    span_id: str = Field(min_length=1, max_length=160)
    parent_id: str | None = Field(default=None, max_length=160)
    span_type: Literal["agent", "llm", "tool", "error"]
    name: str = Field(min_length=1, max_length=160)
    started_at: datetime
    finished_at: datetime
    status: str = Field(min_length=1, max_length=64)
    input_digest: str | None = Field(default=None, min_length=64, max_length=64)
    output_digest: str | None = Field(default=None, min_length=64, max_length=64)
    summary: str = Field(default="", max_length=320)


class OpikFeedback(VersionedModel):
    """写入 Opik 的受控反馈，不能反向改变本地正式结果。"""

    name: str = Field(min_length=1, max_length=160)
    value: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = Field(default=None, min_length=1, max_length=320)


class OpikTracePayload(VersionedModel):
    """宿主侧批量发布的脱敏 trace payload，可独立重试。"""

    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=160)
    attempt: int = Field(ge=1)
    commit_sha: str = Field(min_length=7, max_length=128)
    profile_fingerprint: str = Field(min_length=64, max_length=64)
    spans: tuple[OpikSpan, ...] = Field(min_length=1, max_length=257)
    feedback: tuple[OpikFeedback, ...] = Field(default=(), max_length=256)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=64)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _reject_sensitive_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = VersionedModel._forbidden_extension_key_parts
        for key, item in value.items():
            if len(key) > 160 or len(item) > 320:
                raise ValueError("Opik metadata entries exceed the safe bound")
            if any(part in str(key).casefold() for part in forbidden):
                raise ValueError(
                    "Opik metadata cannot contain credential or session keys"
                )
        return value


class OpikExportResult(VersionedModel):
    """Opik 发布状态；失败不会改变 Harbor/Harness/DeepEval 结果。"""

    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=160)
    status: OpikExportStatus
    payload_digest: str = Field(min_length=64, max_length=64)
    trace_id: str | None = Field(default=None, max_length=160)
    workspace: str | None = Field(default=None, max_length=160)
    project: str | None = Field(default=None, max_length=160)
    attempts: int = Field(default=0, ge=0)
    failure_source: FailureSource | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def _validate_export(self) -> OpikExportResult:
        if self.status is OpikExportStatus.EXPORTED and not self.trace_id:
            raise ValueError("exported Opik result requires trace_id")
        if self.status is not OpikExportStatus.EXPORTED and self.reason is None:
            raise ValueError("failed Opik export requires a reason")
        if self.status is OpikExportStatus.EXPORTED and self.failure_source is not None:
            raise ValueError("exported Opik results cannot carry a failure source")
        if self.status is not OpikExportStatus.EXPORTED and self.failure_source is None:
            raise ValueError("failed Opik export requires a failure source")
        return self


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
    def _enforce_official_isolation(self) -> TaskResult:
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
    """受控规则可生成候选标签，但是否回流仍须经人工复现与审查。"""

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
    """回归门禁的可序列化结论。"""

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
    def _validate_counts(self) -> OfficialScore:
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
    def _validate_report_scope(self) -> EvaluationReport:
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


class VerifiedEvaluationReport(VersionedModel):
    """Verified 单题阶段结果的严格组合对象。

    该对象只描述契约和序列化，不代表 Harbor/Harness 已在当前平台执行。
    """

    manifest: ExperimentManifest
    task_result: TaskResult
    status: ReportStatus
    provenance: VerifiedProvenance | None = None
    trial: TrialExecution | None = None
    harbor: HarborRoutineVerifierResult | None = None
    harness: HarnessRecheckResult | None = None
    deepeval: DeepEvalAnalysis | None = None
    opik: OpikExportResult | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_verified_report(self) -> VerifiedEvaluationReport:
        if self.task_result.task_id not in self.manifest.task_ids:
            raise ValueError("Verified report task is outside its manifest")
        if self.task_result.official and self.status is not ReportStatus.OFFICIAL:
            raise ValueError("official task result requires official report status")
        if not self.task_result.official and self.status is ReportStatus.OFFICIAL:
            raise ValueError("offline task result cannot use official report status")
        return self
