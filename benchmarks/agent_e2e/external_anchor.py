"""冻结 SWE-bench-Live 外部锚点，并把官方结果归一为评测协议。"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from .models import (
    ResultValidity,
    TaskResult,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
    VersionedModel,
)

ANCHOR_ASSET_PATH = (
    Path(__file__).with_name("external_anchor_assets")
    / "swe_bench_live_verified.v1.json"
)
EXPECTED_ANCHOR_FINGERPRINT = "76dad669955ee1dcde77f8c5ee73b6c5f22800e8e504f2616773edcfdbecab9e"
REQUIRED_STRATA = ("files_1", "files_2", "files_3_4", "files_5_plus")
OFFICIAL_EVALUATOR_SUMMARY = "official SWE-bench-Live evaluator"


class ExternalAnchorError(ValueError):
    """外部锚点的冻结输入、官方输出或校准输入不符合契约。"""


class ExternalAnchorDriftError(ExternalAnchorError):
    """两次外部运行的环境指纹不同，不能比较成功率。"""


class OfficialEvaluatorUnavailable(RuntimeError):
    """官方 evaluator 或 Docker daemon 不可用。"""


class AnchorRunStatus(str, Enum):
    """外部锚点运行的受控生命周期状态。"""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    INVALID = "invalid"


class OfficialRecordStatus(str, Enum):
    """官方 evaluator 单实例输出的完整度。"""

    COMPLETED = "completed"
    ERROR = "error"
    INCOMPLETE = "incomplete"


class CalibrationProfileKind(str, Enum):
    """校准 profile 的角色，确保包含刻意退化的反例。"""

    BASELINE = "baseline"
    CANDIDATE = "candidate"
    DEGRADED = "degraded"


class ExternalAnchorInstance(VersionedModel):
    """冻结的一条公开 SWE-bench-Live 元数据，不保存 patch 或测试日志。"""

    instance_id: str = Field(min_length=1, max_length=160)
    repository: str = Field(min_length=1, max_length=240)
    base_commit: str = Field(min_length=40, max_length=40)
    created_at: str = Field(min_length=10, max_length=64)
    difficulty_files: int = Field(ge=1)
    difficulty_hunks: int = Field(ge=1)
    difficulty_lines: int = Field(ge=1)
    stratum: Literal["files_1", "files_2", "files_3_4", "files_5_plus"]
    image_reference: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def _validate_derived_fields(self) -> ExternalAnchorInstance:
        if self.stratum != _stratum_for_files(self.difficulty_files):
            raise ValueError("Anchor stratum does not match difficulty_files")
        expected_image = official_image_reference(self.instance_id, platform="linux")
        if self.image_reference != expected_image:
            raise ValueError("Anchor image_reference does not match official naming rule")
        return self


class ExternalAnchorManifest(VersionedModel):
    """不可变的 20 条 Python-only 外部锚点输入。"""

    anchor_id: str = Field(min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1, max_length=240)
    dataset_revision: str = Field(min_length=40, max_length=40)
    dataset_split: str = Field(min_length=1, max_length=80)
    dataset_file: str = Field(min_length=1, max_length=320)
    dataset_file_sha256: str = Field(min_length=64, max_length=64)
    selected_rows_sha256: str = Field(min_length=64, max_length=64)
    dataset_rows: int = Field(ge=20)
    evaluator_repository: str = Field(min_length=1, max_length=320)
    evaluator_revision: str = Field(min_length=40, max_length=40)
    evaluator_entrypoint: str = Field(min_length=1, max_length=160)
    platform: Literal["linux"]
    selection_seed: str = Field(min_length=1, max_length=160)
    selection_rule: str = Field(min_length=1, max_length=800)
    instances: tuple[ExternalAnchorInstance, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def _validate_frozen_selection(self) -> ExternalAnchorManifest:
        if self.dataset_id != "SWE-bench-Live/SWE-bench-Live":
            raise ValueError("External anchor must use the Python-only SWE-bench-Live dataset")
        if self.dataset_split != "verified":
            raise ValueError("External anchor must use the frozen verified split")
        if self.platform != "linux":
            raise ValueError("External anchor platform must be linux")
        identifiers = [item.instance_id for item in self.instances]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("External anchor instance IDs must be unique")
        repositories = [item.repository.casefold() for item in self.instances]
        if len(set(repositories)) != len(repositories):
            raise ValueError("External anchor selection must not repeat a repository")
        expected_counts = Counter({stratum: 5 for stratum in REQUIRED_STRATA})
        actual_counts = Counter(item.stratum for item in self.instances)
        if actual_counts != expected_counts:
            raise ValueError("External anchor must contain five instances per difficulty stratum")
        return self

    @property
    def instance_ids(self) -> tuple[str, ...]:
        """返回冻结顺序的 instance ID，作为 evaluator 的唯一选择输入。"""

        return tuple(item.instance_id for item in self.instances)

    @property
    def instance_by_id(self) -> dict[str, ExternalAnchorInstance]:
        """返回防御性 ID 索引，避免调用方依赖 live 数据集排序。"""

        return {item.instance_id: item for item in self.instances}


class OfficialEvaluationRecord(VersionedModel):
    """一条官方 evaluator 结果的受控摘要，不保存 raw patch 或 raw log。"""

    instance_id: str = Field(min_length=1, max_length=160)
    status: OfficialRecordStatus
    resolved: bool | None = None
    output_digest: str = Field(min_length=64, max_length=64)
    command_digest: str = Field(min_length=64, max_length=64)
    image_reference: str = Field(min_length=1, max_length=320)
    image_digest: str | None = Field(default=None, min_length=7, max_length=320)
    reason: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _validate_completion(self) -> OfficialEvaluationRecord:
        if self.status is OfficialRecordStatus.COMPLETED:
            if self.resolved is None:
                raise ValueError("Completed official record requires resolved")
            if self.reason is not None:
                raise ValueError("Completed official record cannot carry an error reason")
        elif self.reason is None:
            raise ValueError("Incomplete official record requires a controlled reason")
        return self


class GoldPreflightEntry(VersionedModel):
    """同一实例恰好三次 gold patch 预检的归一化证据。"""

    instance_id: str = Field(min_length=1, max_length=160)
    records: tuple[OfficialEvaluationRecord, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _validate_records(self) -> GoldPreflightEntry:
        if any(record.instance_id != self.instance_id for record in self.records):
            raise ValueError("Gold preflight records must belong to their entry instance")
        return self

    @property
    def stable(self) -> bool:
        """仅三次都由官方 evaluator 判为 resolved 才算本机可用 gold。"""

        return all(
            record.status is OfficialRecordStatus.COMPLETED and record.resolved is True
            for record in self.records
        )


class GoldPreflightReport(VersionedModel):
    """所有冻结实例的三次 gold 预检，不把不稳定案例计入分母。"""

    manifest_fingerprint: str = Field(min_length=64, max_length=64)
    status: AnchorRunStatus
    entries: tuple[GoldPreflightEntry, ...] = ()
    blocked_reason: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _validate_state(self) -> GoldPreflightReport:
        if self.status is AnchorRunStatus.BLOCKED:
            if self.entries or not self.blocked_reason:
                raise ValueError("Blocked gold preflight requires reason and no entries")
        elif self.blocked_reason is not None:
            raise ValueError("Only blocked gold preflight may carry blocked_reason")
        return self

    @property
    def stable_instance_ids(self) -> tuple[str, ...]:
        """返回此机此时可以进入外部成功率分母的实例。"""

        return tuple(entry.instance_id for entry in self.entries if entry.stable)


class ExternalImage(VersionedModel):
    """已解析的官方实例镜像，不依赖易变 tag 作为比较依据。"""

    instance_id: str = Field(min_length=1, max_length=160)
    image_reference: str = Field(min_length=1, max_length=320)
    image_digest: str = Field(min_length=7, max_length=320)


class ExternalAnchorEnvironment(VersionedModel):
    """决定外部结果可比性的完整环境指纹。"""

    manifest_fingerprint: str = Field(min_length=64, max_length=64)
    dataset_revision: str = Field(min_length=40, max_length=40)
    dataset_file_sha256: str = Field(min_length=64, max_length=64)
    evaluator_revision: str = Field(min_length=40, max_length=40)
    platform: Literal["linux"]
    images: tuple[ExternalImage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_images(self) -> ExternalAnchorEnvironment:
        instance_ids = [image.instance_id for image in self.images]
        if len(set(instance_ids)) != len(instance_ids):
            raise ValueError("External environment image records must be unique")
        return self


class ConfidenceInterval(VersionedModel):
    """成功率的 Wilson 95% 区间。"""

    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_order(self) -> ConfidenceInterval:
        if self.lower > self.upper:
            raise ValueError("Confidence interval lower bound exceeds upper bound")
        return self


class ExternalAnchorReport(VersionedModel):
    """外部锚点正式报告；没有完整官方结果时绝不携带成功率。"""

    manifest_fingerprint: str = Field(min_length=64, max_length=64)
    status: AnchorRunStatus
    gold_preflight: GoldPreflightReport
    task_results: tuple[TaskResult, ...] = ()
    valid_denominator: int = Field(ge=0)
    passed: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    success_interval: ConfidenceInterval | None = None
    environment: ExternalAnchorEnvironment | None = None
    reason: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _validate_report(self) -> ExternalAnchorReport:
        if self.gold_preflight.manifest_fingerprint != self.manifest_fingerprint:
            raise ValueError("Gold preflight must use the same frozen manifest")
        if self.status is AnchorRunStatus.COMPLETED:
            if self.valid_denominator <= 0:
                raise ValueError("Completed external report requires a positive denominator")
            if self.success_rate is None or self.success_interval is None or self.environment is None:
                raise ValueError("Completed external report requires score, interval and environment")
            if self.passed > self.valid_denominator:
                raise ValueError("Passed count exceeds external denominator")
            expected_rate = self.passed / self.valid_denominator
            if not math.isclose(self.success_rate, expected_rate, abs_tol=1e-12):
                raise ValueError("External success rate does not match numerator and denominator")
            if self.environment.manifest_fingerprint != self.manifest_fingerprint:
                raise ValueError("External environment must use the same frozen manifest")
            if self.reason is not None:
                raise ValueError("Completed external report cannot carry an error reason")
        elif self.success_rate is not None or self.success_interval is not None:
            raise ValueError("Blocked or invalid external reports cannot report a success rate")
        return self


class CalibrationPoint(VersionedModel):
    """一个冻结 profile 在自建 holdout 与外部锚点上的可比较分数。"""

    profile_id: str = Field(min_length=1, max_length=128)
    profile_fingerprint: str = Field(min_length=64, max_length=64)
    profile_kind: CalibrationProfileKind
    self_holdout_passed: int = Field(ge=0)
    self_holdout_denominator: int = Field(gt=0)
    external_report_fingerprint: str = Field(min_length=64, max_length=64)
    external_passed: int = Field(ge=0)
    external_denominator: int = Field(gt=0)
    external_success_rate: float = Field(ge=0, le=1)
    environment: ExternalAnchorEnvironment

    @model_validator(mode="after")
    def _validate_rates(self) -> CalibrationPoint:
        if self.self_holdout_passed > self.self_holdout_denominator:
            raise ValueError("Self holdout passed count exceeds denominator")
        if self.external_passed > self.external_denominator:
            raise ValueError("External passed count exceeds denominator")
        if not math.isclose(
            self.external_success_rate,
            self.external_passed / self.external_denominator,
            abs_tol=1e-12,
        ):
            raise ValueError("External calibration score does not match numerator and denominator")
        return self

    @property
    def self_holdout_success_rate(self) -> float:
        """返回同 profile 的自建 holdout 成功率。"""

        return self.self_holdout_passed / self.self_holdout_denominator


class CalibrationReport(VersionedModel):
    """至少五个 profile 的外部有效性校准结论。"""

    points: tuple[CalibrationPoint, ...] = Field(min_length=5)
    spearman_rho: float | None = Field(default=None, ge=-1, le=1)
    direction_pairs: int = Field(ge=0)
    direction_agreement: float | None = Field(default=None, ge=0, le=1)
    accepted: bool


@runtime_checkable
class OfficialSWEbenchLiveRunner(Protocol):
    """官方 evaluator 的最小 host 边界；Agent 无法获取这个对象或输出目录。"""

    @property
    def available(self) -> bool:
        """Docker、官方 checkout 和其入口是否都可用。"""
        ...

    @property
    def unavailable_reason(self) -> str | None:
        """不可用时给出不含凭证或绝对路径的原因。"""
        ...

    def evaluate(
        self,
        *,
        manifest: ExternalAnchorManifest,
        patch_source: str | Path,
        instance_ids: Sequence[str],
        output_dir: Path,
        workers: int,
    ) -> tuple[OfficialEvaluationRecord, ...]:
        """调用官方 patch evaluator 并返回已脱敏的每实例摘要。"""
        ...


class UnavailableOfficialSWEbenchLiveRunner:
    """Docker/evaluator 未准备好时的显式 runner，永不尝试降级为 host 测试。"""

    def __init__(self, reason: str = "Docker daemon or official evaluator is unavailable") -> None:
        self._reason = reason

    @property
    def available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def evaluate(
        self,
        *,
        manifest: ExternalAnchorManifest,
        patch_source: str | Path,
        instance_ids: Sequence[str],
        output_dir: Path,
        workers: int,
    ) -> tuple[OfficialEvaluationRecord, ...]:
        raise OfficialEvaluatorUnavailable(self._reason)


class SubprocessOfficialSWEbenchLiveRunner:
    """通过固定 checkout 调用官方 evaluator；只在 daemon 已可用时运行。"""

    def __init__(
        self,
        *,
        evaluator_root: str | Path,
        dataset_jsonl: str | Path,
        python_executable: str = sys.executable,
        docker_executable: str = "docker",
        timeout_seconds: int = 10_800,
    ) -> None:
        self._evaluator_root = Path(evaluator_root)
        self._dataset_jsonl = Path(dataset_jsonl)
        self._python_executable = python_executable
        self._docker_executable = docker_executable
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        entrypoint = self._evaluator_root / "evaluation" / "evaluation.py"
        if not entrypoint.is_file():
            return "Official SWE-bench-Live evaluator checkout is unavailable"
        if not self._dataset_jsonl.is_file():
            return "Pinned SWE-bench-Live JSONL snapshot is unavailable"
        if shutil.which(self._docker_executable) is None:
            return "Docker CLI is unavailable"
        try:
            probe = subprocess.run(
                [self._docker_executable, "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except OSError:
            return "Docker daemon probe could not start"
        except subprocess.TimeoutExpired:
            return "Docker daemon probe timed out"
        if probe.returncode:
            return "Docker daemon is unavailable"
        return None

    def evaluate(
        self,
        *,
        manifest: ExternalAnchorManifest,
        patch_source: str | Path,
        instance_ids: Sequence[str],
        output_dir: Path,
        workers: int,
    ) -> tuple[OfficialEvaluationRecord, ...]:
        reason = self.unavailable_reason
        if reason is not None:
            raise OfficialEvaluatorUnavailable(reason)
        if not instance_ids:
            raise ExternalAnchorError("Official evaluator needs at least one selected instance")
        if workers < 1:
            raise ExternalAnchorError("Official evaluator workers must be positive")
        unknown = set(instance_ids).difference(manifest.instance_ids)
        if unknown:
            raise ExternalAnchorError(f"Official evaluator received unfrozen IDs: {sorted(unknown)!r}")
        validate_materialized_dataset_snapshot(manifest, self._dataset_jsonl)

        output_dir.mkdir(parents=True, exist_ok=True)
        command = _official_command(
            manifest=manifest,
            dataset_source=self._dataset_jsonl,
            patch_source=patch_source,
            instance_ids=instance_ids,
            output_dir=output_dir,
            workers=workers,
            python_executable=self._python_executable,
        )
        command_digest = _digest_json(command)
        try:
            completed = subprocess.run(
                command,
                cwd=self._evaluator_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return tuple(
                _error_record(
                    instance_id,
                    manifest.instance_by_id[instance_id],
                    command_digest,
                    "Official evaluator timed out",
                )
                for instance_id in instance_ids
            )
        except OSError:
            return tuple(
                _error_record(
                    instance_id,
                    manifest.instance_by_id[instance_id],
                    command_digest,
                    "Official evaluator process could not start",
                )
                for instance_id in instance_ids
            )

        if completed.returncode:
            return tuple(
                _error_record(
                    instance_id,
                    manifest.instance_by_id[instance_id],
                    command_digest,
                    "Official evaluator exited unsuccessfully",
                )
                for instance_id in instance_ids
            )
        return tuple(
            _record_from_report(
                instance_id=instance_id,
                instance=manifest.instance_by_id[instance_id],
                report_path=output_dir / instance_id / "report.json",
                command_digest=command_digest,
                docker_executable=self._docker_executable,
            )
            for instance_id in instance_ids
        )


def official_image_reference(instance_id: str, *, platform: Literal["linux"] = "linux") -> str:
    """复用官方 evaluator 的 Linux 镜像命名规则。"""

    if platform != "linux":
        raise ExternalAnchorError("The frozen external anchor only supports linux")
    return f"starryzhang/sweb.eval.x86_64.{instance_id.replace('__', '_1776_').lower()}"


def select_external_anchor_instances(
    rows: Iterable[Mapping[str, Any]],
    *,
    seed: str,
    per_stratum: int = 5,
) -> tuple[ExternalAnchorInstance, ...]:
    """从已冻结的行元数据确定性选样，不读取或保留 gold/测试 patch。"""

    if not seed:
        raise ExternalAnchorError("External anchor selection seed cannot be empty")
    if per_stratum != 5:
        raise ExternalAnchorError("V1 external anchor requires exactly five instances per stratum")

    candidates: list[ExternalAnchorInstance] = []
    seen_by_id: dict[str, ExternalAnchorInstance] = {}
    for row in rows:
        item = _instance_from_dataset_row(row)
        previous = seen_by_id.get(item.instance_id)
        if previous is not None:
            if previous != item:
                raise ExternalAnchorError(
                    f"Dataset snapshot has conflicting metadata for {item.instance_id}"
                )
            continue
        seen_by_id[item.instance_id] = item
        candidates.append(item)

    selected: list[ExternalAnchorInstance] = []
    used_repositories: set[str] = set()
    for stratum in REQUIRED_STRATA:
        stratum_candidates = sorted(
            (item for item in candidates if item.stratum == stratum),
            key=lambda item: (_sha256_text(f"{seed}|{item.instance_id}"), item.instance_id),
        )
        for item in stratum_candidates:
            repository_key = item.repository.casefold()
            if repository_key in used_repositories:
                continue
            selected.append(item)
            used_repositories.add(repository_key)
            if sum(entry.stratum == stratum for entry in selected) == per_stratum:
                break
        if sum(entry.stratum == stratum for entry in selected) != per_stratum:
            raise ExternalAnchorError(f"Not enough distinct repositories in {stratum}")
    return tuple(selected)


def load_bundled_external_anchor_manifest() -> ExternalAnchorManifest:
    """读取仓库提交的冻结 20 题清单；调用方不访问 live 数据源。"""

    return ExternalAnchorManifest.from_json(ANCHOR_ASSET_PATH.read_text(encoding="utf-8"))


def validate_bundled_external_anchor_manifest() -> ExternalAnchorManifest:
    """验证内置清单的内容指纹、配额、ID、镜像名和静态 schema。"""

    manifest = load_bundled_external_anchor_manifest()
    if EXPECTED_ANCHOR_FINGERPRINT and manifest.fingerprint() != EXPECTED_ANCHOR_FINGERPRINT:
        raise ExternalAnchorError("Bundled external anchor manifest fingerprint drifted")
    return manifest


def validate_manifest_against_snapshot(
    manifest: ExternalAnchorManifest,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """把冻结的 20 条元数据与同一 revision 的完整数据快照交叉校验。"""

    snapshot = tuple(rows)
    if len(snapshot) != manifest.dataset_rows:
        raise ExternalAnchorDriftError("Dataset row count differs from frozen external manifest")
    frozen_ids = set(manifest.instance_ids)
    selected_by_id: dict[str, Mapping[str, Any]] = {}
    for row in snapshot:
        if not isinstance(row, Mapping):
            continue
        instance_id = str(row.get("instance_id", ""))
        if instance_id not in frozen_ids:
            continue
        previous = selected_by_id.get(instance_id)
        if previous is not None and _digest_json(previous) != _digest_json(row):
            raise ExternalAnchorDriftError(
                f"Frozen instance appears with conflicting content: {instance_id}"
            )
        selected_by_id[instance_id] = row
    if set(selected_by_id) != frozen_ids:
        missing = sorted(frozen_ids.difference(selected_by_id))
        raise ExternalAnchorDriftError(f"Frozen instances disappeared: {missing!r}")
    for expected in manifest.instances:
        if _instance_from_dataset_row(selected_by_id[expected.instance_id]) != expected:
            raise ExternalAnchorDriftError(f"Frozen instance metadata drifted: {expected.instance_id}")
    if _canonical_rows_digest(selected_by_id.values()) != manifest.selected_rows_sha256:
        raise ExternalAnchorDriftError("Frozen selected-row content drifted")


def write_materialized_dataset_snapshot(
    manifest: ExternalAnchorManifest,
    rows: Iterable[Mapping[str, Any]],
    *,
    output_path: str | Path,
) -> Path:
    """把已按 manifest revision 获取的 20 条完整行写成官方 evaluator 可用的 JSONL。"""

    frozen_rows = _validate_materialized_rows(manifest, tuple(rows))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in frozen_rows
        ),
        encoding="utf-8",
    )
    return path


def validate_materialized_dataset_snapshot(
    manifest: ExternalAnchorManifest,
    dataset_jsonl: str | Path,
) -> None:
    """校验官方 evaluator 将读取的本地 JSONL 与冻结 revision 的选择内容完全一致。"""

    path = Path(dataset_jsonl)
    try:
        rows = tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except OSError as error:
        raise ExternalAnchorError("Pinned SWE-bench-Live JSONL snapshot is unavailable") from error
    except json.JSONDecodeError as error:
        raise ExternalAnchorError("Pinned SWE-bench-Live JSONL snapshot is invalid JSONL") from error
    _validate_materialized_rows(manifest, rows)


def run_gold_preflight(
    manifest: ExternalAnchorManifest,
    *,
    runner: OfficialSWEbenchLiveRunner,
    output_root: str | Path,
    workers: int = 1,
) -> GoldPreflightReport:
    """以官方 gold patch 恰跑三次，返回本机实际稳定分母。"""

    manifest_fingerprint = manifest.fingerprint()
    if not runner.available:
        return GoldPreflightReport(
            manifest_fingerprint=manifest_fingerprint,
            status=AnchorRunStatus.BLOCKED,
            blocked_reason=runner.unavailable_reason or "Official evaluator is unavailable",
        )

    records_by_id: dict[str, list[OfficialEvaluationRecord]] = {
        instance_id: [] for instance_id in manifest.instance_ids
    }
    root = Path(output_root)
    try:
        for repeat in range(1, 4):
            records = runner.evaluate(
                manifest=manifest,
                patch_source="gold",
                instance_ids=manifest.instance_ids,
                output_dir=root / "gold-preflight" / f"repeat-{repeat}",
                workers=workers,
            )
            normalized = _normalize_records(manifest, records, expected_ids=manifest.instance_ids)
            for instance_id, record in normalized.items():
                records_by_id[instance_id].append(record)
    except OfficialEvaluatorUnavailable as error:
        return GoldPreflightReport(
            manifest_fingerprint=manifest_fingerprint,
            status=AnchorRunStatus.BLOCKED,
            blocked_reason=_controlled_reason(error),
        )
    except (ExternalAnchorError, OSError, ValueError) as error:
        return _invalid_gold_preflight(manifest, _controlled_reason(error))

    entries = tuple(
        GoldPreflightEntry(instance_id=instance_id, records=tuple(records_by_id[instance_id]))
        for instance_id in manifest.instance_ids
    )
    return GoldPreflightReport(
        manifest_fingerprint=manifest_fingerprint,
        status=AnchorRunStatus.COMPLETED,
        entries=entries,
    )


def run_external_anchor_evaluation(
    manifest: ExternalAnchorManifest,
    *,
    runner: OfficialSWEbenchLiveRunner,
    prediction_path: str | Path,
    output_root: str | Path,
    workers: int = 1,
) -> ExternalAnchorReport:
    """先 gold 预检，再由官方 evaluator 评价预测 patch；禁止 host 降级评分。"""

    manifest_fingerprint = manifest.fingerprint()
    gold_preflight = run_gold_preflight(
        manifest,
        runner=runner,
        output_root=output_root,
        workers=workers,
    )
    if gold_preflight.status is AnchorRunStatus.BLOCKED:
        return _blocked_anchor_report(manifest, gold_preflight)

    stable_ids = gold_preflight.stable_instance_ids
    if not stable_ids:
        return _invalid_anchor_report(
            manifest,
            gold_preflight,
            task_results=tuple(
                _invalid_task_result(
                    instance_id,
                    "Gold patch did not pass all three official preflight runs",
                )
                for instance_id in manifest.instance_ids
            ),
            reason="No instance passed gold patch preflight three times",
        )

    try:
        patch_digests = load_prediction_patch_digests(prediction_path, manifest=manifest)
        records = runner.evaluate(
            manifest=manifest,
            patch_source=Path(prediction_path),
            instance_ids=stable_ids,
            output_dir=Path(output_root) / "model-evaluation",
            workers=workers,
        )
        normalized = _normalize_records(manifest, records, expected_ids=stable_ids)
    except OfficialEvaluatorUnavailable as error:
        return _blocked_anchor_report(
            manifest,
            GoldPreflightReport(
                manifest_fingerprint=manifest_fingerprint,
                status=AnchorRunStatus.BLOCKED,
                blocked_reason=_controlled_reason(error),
            ),
        )
    except (ExternalAnchorError, OSError, ValueError) as error:
        return _invalid_anchor_report(
            manifest,
            gold_preflight,
            task_results=tuple(
                _invalid_task_result(instance_id, _controlled_reason(error))
                for instance_id in stable_ids
            ),
            reason=_controlled_reason(error),
        )

    task_results: list[TaskResult] = []
    stable_set = set(stable_ids)
    for instance_id in manifest.instance_ids:
        if instance_id not in stable_set:
            task_results.append(
                _invalid_task_result(
                    instance_id,
                    "Gold patch did not pass all three official preflight runs",
                )
            )
            continue
        task_results.append(
            _task_result_from_official_record(
                manifest,
                normalized[instance_id],
                patch_sha256=patch_digests[instance_id],
            )
        )

    official_results = [
        result
        for result in task_results
        if result.task_id in stable_set and result.official
    ]
    if len(official_results) != len(stable_ids):
        return _invalid_anchor_report(
            manifest,
            gold_preflight,
            task_results=tuple(task_results),
            reason="Official evaluator did not complete every gold-stable instance",
        )
    try:
        environment = _build_environment(manifest, normalized, stable_ids)
    except ExternalAnchorError as error:
        return _invalid_anchor_report(
            manifest,
            gold_preflight,
            task_results=tuple(task_results),
            reason=_controlled_reason(error),
        )

    passed = sum(result.verdict is TaskVerdict.PASSED for result in official_results)
    denominator = len(stable_ids)
    return ExternalAnchorReport(
        manifest_fingerprint=manifest_fingerprint,
        status=AnchorRunStatus.COMPLETED,
        gold_preflight=gold_preflight,
        task_results=tuple(task_results),
        valid_denominator=denominator,
        passed=passed,
        success_rate=passed / denominator,
        success_interval=wilson_95_interval(passed, denominator),
        environment=environment,
    )


def load_prediction_patch_digests(
    prediction_path: str | Path,
    *,
    manifest: ExternalAnchorManifest,
) -> dict[str, str]:
    """验证官方 prediction JSON 形状，只返回每条 patch 摘要而不持久化正文。"""

    path = Path(prediction_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ExternalAnchorError("Prediction patch file is unavailable") from error
    except json.JSONDecodeError as error:
        raise ExternalAnchorError("Prediction patch file is invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise ExternalAnchorError("Prediction patch file must be a JSON object")
    supplied_ids = set(payload)
    expected_ids = set(manifest.instance_ids)
    if supplied_ids != expected_ids:
        raise ExternalAnchorError("Prediction patch IDs must exactly match the frozen anchor")
    digests: dict[str, str] = {}
    for instance_id in manifest.instance_ids:
        item = payload[instance_id]
        patch = item.get("model_patch") if isinstance(item, Mapping) else None
        if not isinstance(patch, str):
            raise ExternalAnchorError(f"Prediction patch is missing model_patch for {instance_id}")
        digests[instance_id] = _sha256_text(patch)
    return digests


def make_calibration_point(
    *,
    profile_id: str,
    profile_fingerprint: str,
    profile_kind: CalibrationProfileKind,
    self_holdout_passed: int,
    self_holdout_denominator: int,
    external_report: ExternalAnchorReport,
) -> CalibrationPoint:
    """只允许完整、可比的外部报告进入 profile 校准。"""

    if external_report.status is not AnchorRunStatus.COMPLETED:
        raise ExternalAnchorError("Calibration requires a completed external anchor report")
    if external_report.environment is None or external_report.success_rate is None:
        raise ExternalAnchorError("Calibration requires external environment and success rate")
    return CalibrationPoint(
        profile_id=profile_id,
        profile_fingerprint=profile_fingerprint,
        profile_kind=profile_kind,
        self_holdout_passed=self_holdout_passed,
        self_holdout_denominator=self_holdout_denominator,
        external_report_fingerprint=external_report.fingerprint(),
        external_passed=external_report.passed,
        external_denominator=external_report.valid_denominator,
        external_success_rate=external_report.success_rate,
        environment=external_report.environment,
    )


def calibrate_external_anchor(points: Iterable[CalibrationPoint]) -> CalibrationReport:
    """计算排名与方向一致性，并强制 baseline/candidate/degraded 校准覆盖。"""

    frozen_points = tuple(points)
    if len(frozen_points) < 5:
        raise ExternalAnchorError("External calibration requires at least five frozen profiles")
    if len({point.profile_fingerprint for point in frozen_points}) != len(frozen_points):
        raise ExternalAnchorError("External calibration profile fingerprints must be unique")
    kinds = Counter(point.profile_kind for point in frozen_points)
    if kinds[CalibrationProfileKind.BASELINE] < 1:
        raise ExternalAnchorError("External calibration requires a baseline profile")
    if kinds[CalibrationProfileKind.CANDIDATE] < 3:
        raise ExternalAnchorError("External calibration requires at least three candidate profiles")
    if kinds[CalibrationProfileKind.DEGRADED] < 1:
        raise ExternalAnchorError("External calibration requires a deliberately degraded profile")
    reference_environment = frozen_points[0].environment
    for point in frozen_points[1:]:
        _require_same_environment(reference_environment, point.environment)

    self_scores = [point.self_holdout_success_rate for point in frozen_points]
    external_scores = [point.external_success_rate for point in frozen_points]
    rho = _spearman_rho(self_scores, external_scores)
    direction_pairs, direction_agreement = _direction_agreement(self_scores, external_scores)
    accepted = (
        rho is not None
        and rho >= 0.70
        and direction_agreement is not None
        and direction_agreement >= 0.80
    )
    return CalibrationReport(
        points=frozen_points,
        spearman_rho=rho,
        direction_pairs=direction_pairs,
        direction_agreement=direction_agreement,
        accepted=accepted,
    )


def require_comparable_external_reports(
    baseline: ExternalAnchorReport,
    candidate: ExternalAnchorReport,
) -> None:
    """比较通过率前严格检查数据、evaluator、平台、抽样和镜像是否完全一致。"""

    if baseline.status is not AnchorRunStatus.COMPLETED or candidate.status is not AnchorRunStatus.COMPLETED:
        raise ExternalAnchorDriftError("Only completed external reports are comparable")
    if baseline.environment is None or candidate.environment is None:
        raise ExternalAnchorDriftError("External report is missing an environment fingerprint")
    _require_same_environment(baseline.environment, candidate.environment)


def wilson_95_interval(passed: int, denominator: int) -> ConfidenceInterval:
    """计算二项成功率的 Wilson 95% 区间；零分母没有统计含义。"""

    if denominator <= 0 or passed < 0 or passed > denominator:
        raise ExternalAnchorError("Wilson interval needs 0 <= passed <= denominator and denominator > 0")
    z = 1.959963984540054
    proportion = passed / denominator
    denominator_adjusted = 1 + z * z / denominator
    center = (proportion + z * z / (2 * denominator)) / denominator_adjusted
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator
            + z * z / (4 * denominator * denominator)
        )
        / denominator_adjusted
    )
    return ConfidenceInterval(lower=max(0.0, center - margin), upper=min(1.0, center + margin))


def write_external_anchor_report(
    report: ExternalAnchorReport,
    *,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """写入 JSON/Markdown 受控报告；不复制 runner 的原始 patch 或测试日志。"""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "external_anchor_report.json"
    markdown_path = directory / "external_anchor_report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_anchor_report_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _instance_from_dataset_row(row: Mapping[str, Any]) -> ExternalAnchorInstance:
    try:
        difficulty = row["difficulty"]
        if not isinstance(difficulty, Mapping):
            raise TypeError("difficulty is not a mapping")
        instance_id = str(row["instance_id"])
        return ExternalAnchorInstance(
            instance_id=instance_id,
            repository=str(row["repo"]),
            base_commit=str(row["base_commit"]),
            created_at=str(row["created_at"]),
            difficulty_files=int(difficulty["files"]),
            difficulty_hunks=int(difficulty["hunks"]),
            difficulty_lines=int(difficulty["lines"]),
            stratum=_stratum_for_files(int(difficulty["files"])),
            image_reference=official_image_reference(instance_id),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ExternalAnchorError("Dataset row lacks frozen anchor metadata") from error


def _validate_materialized_rows(
    manifest: ExternalAnchorManifest,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if len(rows) != len(manifest.instances):
        raise ExternalAnchorDriftError("Materialized external snapshot must contain exactly 20 rows")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ExternalAnchorDriftError("Materialized external snapshot contains a non-object row")
        instance_id = str(row.get("instance_id", ""))
        if instance_id in by_id:
            raise ExternalAnchorDriftError(f"Materialized external snapshot repeats ID: {instance_id}")
        by_id[instance_id] = row
    if set(by_id) != set(manifest.instance_ids):
        raise ExternalAnchorDriftError("Materialized external snapshot IDs differ from frozen anchor")
    ordered_rows: list[Mapping[str, Any]] = []
    for expected in manifest.instances:
        row = by_id[expected.instance_id]
        if _instance_from_dataset_row(row) != expected:
            raise ExternalAnchorDriftError(
                f"Materialized external snapshot metadata drifted: {expected.instance_id}"
            )
        ordered_rows.append(row)
    if _canonical_rows_digest(ordered_rows) != manifest.selected_rows_sha256:
        raise ExternalAnchorDriftError("Materialized external snapshot content hash differs from frozen manifest")
    return tuple(ordered_rows)


def _canonical_rows_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    ordered_rows = sorted(rows, key=lambda row: str(row.get("instance_id", "")))
    return _digest_json(ordered_rows)


def _stratum_for_files(files: int) -> Literal["files_1", "files_2", "files_3_4", "files_5_plus"]:
    if files == 1:
        return "files_1"
    if files == 2:
        return "files_2"
    if files in {3, 4}:
        return "files_3_4"
    if files >= 5:
        return "files_5_plus"
    raise ExternalAnchorError("difficulty.files must be positive")


def _official_command(
    *,
    manifest: ExternalAnchorManifest,
    dataset_source: str | Path,
    patch_source: str | Path,
    instance_ids: Sequence[str],
    output_dir: Path,
    workers: int,
    python_executable: str,
) -> list[str]:
    return [
        python_executable,
        "-m",
        manifest.evaluator_entrypoint,
        "--dataset",
        str(dataset_source),
        "--platform",
        manifest.platform,
        "--patch_dir",
        str(patch_source),
        "--output_dir",
        str(output_dir),
        "--workers",
        str(workers),
        "--overwrite",
        "1",
        "--instance_ids",
        *instance_ids,
    ]


def _record_from_report(
    *,
    instance_id: str,
    instance: ExternalAnchorInstance,
    report_path: Path,
    command_digest: str,
    docker_executable: str,
) -> OfficialEvaluationRecord:
    try:
        raw_report = report_path.read_bytes()
        payload = json.loads(raw_report)
    except (OSError, json.JSONDecodeError):
        return _error_record(
            instance_id,
            instance,
            command_digest,
            "Official evaluator did not write a valid per-instance report",
        )
    resolved = payload.get("resolved") if isinstance(payload, Mapping) else None
    if not isinstance(resolved, bool):
        return _error_record(
            instance_id,
            instance,
            command_digest,
            "Official evaluator report lacks a boolean resolved result",
        )
    return OfficialEvaluationRecord(
        instance_id=instance_id,
        status=OfficialRecordStatus.COMPLETED,
        resolved=resolved,
        output_digest=hashlib.sha256(raw_report).hexdigest(),
        command_digest=command_digest,
        image_reference=instance.image_reference,
        image_digest=_docker_image_digest(docker_executable, instance.image_reference),
    )


def _docker_image_digest(docker_executable: str, image_reference: str) -> str | None:
    try:
        result = subprocess.run(
            [docker_executable, "image", "inspect", "--format", "{{.Id}}", image_reference],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    digest = result.stdout.strip()
    return digest if result.returncode == 0 and digest.startswith("sha256:") else None


def _error_record(
    instance_id: str,
    instance: ExternalAnchorInstance,
    command_digest: str,
    reason: str,
) -> OfficialEvaluationRecord:
    controlled_reason = _controlled_reason(reason)
    return OfficialEvaluationRecord(
        instance_id=instance_id,
        status=OfficialRecordStatus.ERROR,
        output_digest=_sha256_text(controlled_reason),
        command_digest=command_digest,
        image_reference=instance.image_reference,
        reason=controlled_reason,
    )


def _normalize_records(
    manifest: ExternalAnchorManifest,
    records: Iterable[OfficialEvaluationRecord],
    *,
    expected_ids: Sequence[str],
) -> dict[str, OfficialEvaluationRecord]:
    expected = set(expected_ids)
    normalized: dict[str, OfficialEvaluationRecord] = {}
    for record in records:
        if record.instance_id not in expected:
            raise ExternalAnchorError(f"Official evaluator returned an unselected ID: {record.instance_id}")
        if record.instance_id in normalized:
            raise ExternalAnchorError(f"Official evaluator repeated ID: {record.instance_id}")
        expected_instance = manifest.instance_by_id[record.instance_id]
        if record.image_reference != expected_instance.image_reference:
            raise ExternalAnchorError(f"Official evaluator image drifted for {record.instance_id}")
        normalized[record.instance_id] = record
    missing = expected.difference(normalized)
    if missing:
        raise ExternalAnchorError(f"Official evaluator omitted IDs: {sorted(missing)!r}")
    return normalized


def _invalid_gold_preflight(
    manifest: ExternalAnchorManifest,
    reason: str,
) -> GoldPreflightReport:
    fingerprint = manifest.fingerprint()
    entries = tuple(
        GoldPreflightEntry(
            instance_id=instance_id,
            records=tuple(
                _error_record(
                    instance_id,
                    manifest.instance_by_id[instance_id],
                    _sha256_text("gold-preflight-invalid"),
                    reason,
                )
                for _ in range(3)
            ),
        )
        for instance_id in manifest.instance_ids
    )
    return GoldPreflightReport(
        manifest_fingerprint=fingerprint,
        status=AnchorRunStatus.INVALID,
        entries=entries,
    )


def _blocked_anchor_report(
    manifest: ExternalAnchorManifest,
    gold_preflight: GoldPreflightReport,
) -> ExternalAnchorReport:
    reason = gold_preflight.blocked_reason or "Official evaluator is unavailable"
    return ExternalAnchorReport(
        manifest_fingerprint=manifest.fingerprint(),
        status=AnchorRunStatus.BLOCKED,
        gold_preflight=gold_preflight,
        task_results=tuple(
            TaskResult(
                task_id=instance_id,
                attempt=1,
                verdict=TaskVerdict.BLOCKED,
                validity=ResultValidity.BLOCKED,
                official=False,
                invalid_reason=reason,
            )
            for instance_id in manifest.instance_ids
        ),
        valid_denominator=0,
        passed=0,
        reason=reason,
    )


def _invalid_anchor_report(
    manifest: ExternalAnchorManifest,
    gold_preflight: GoldPreflightReport,
    *,
    task_results: tuple[TaskResult, ...],
    reason: str,
) -> ExternalAnchorReport:
    return ExternalAnchorReport(
        manifest_fingerprint=manifest.fingerprint(),
        status=AnchorRunStatus.INVALID,
        gold_preflight=gold_preflight,
        task_results=task_results,
        valid_denominator=len(gold_preflight.stable_instance_ids),
        passed=0,
        reason=_controlled_reason(reason),
    )


def _invalid_task_result(instance_id: str, reason: str) -> TaskResult:
    return TaskResult(
        task_id=instance_id,
        attempt=1,
        verdict=TaskVerdict.INVALID,
        validity=ResultValidity.INVALID,
        official=False,
        invalid_reason=_controlled_reason(reason),
    )


def _task_result_from_official_record(
    manifest: ExternalAnchorManifest,
    record: OfficialEvaluationRecord,
    *,
    patch_sha256: str,
) -> TaskResult:
    if record.status is not OfficialRecordStatus.COMPLETED or record.resolved is None:
        return _invalid_task_result(record.instance_id, record.reason or "Official evaluator result is incomplete")
    outcome = VerifierOutcome.PASSED if record.resolved else VerifierOutcome.FAILED
    verdict = TaskVerdict.PASSED if record.resolved else TaskVerdict.FAILED
    return TaskResult(
        task_id=record.instance_id,
        attempt=1,
        verdict=verdict,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256=patch_sha256,
        verifier=VerifierResult(
            outcome=outcome,
            command_summary=OFFICIAL_EVALUATOR_SUMMARY,
            exit_code=0,
            output_digest=record.output_digest,
            output_preview=f"resolved={str(record.resolved).lower()}",
        ),
        extensions={
            "external_anchor": {
                "manifest_fingerprint": manifest.fingerprint(),
                "dataset_revision": manifest.dataset_revision,
                "evaluator_revision": manifest.evaluator_revision,
                "platform": manifest.platform,
                "image_reference": record.image_reference,
                "image_digest": record.image_digest,
                "official_result_digest": record.output_digest,
            }
        },
    )


def _build_environment(
    manifest: ExternalAnchorManifest,
    records: Mapping[str, OfficialEvaluationRecord],
    stable_ids: Sequence[str],
) -> ExternalAnchorEnvironment:
    images: list[ExternalImage] = []
    for instance_id in stable_ids:
        record = records[instance_id]
        if record.image_digest is None:
            raise ExternalAnchorError(f"Official evaluator did not resolve image digest for {instance_id}")
        images.append(
            ExternalImage(
                instance_id=instance_id,
                image_reference=record.image_reference,
                image_digest=record.image_digest,
            )
        )
    return ExternalAnchorEnvironment(
        manifest_fingerprint=manifest.fingerprint(),
        dataset_revision=manifest.dataset_revision,
        dataset_file_sha256=manifest.dataset_file_sha256,
        evaluator_revision=manifest.evaluator_revision,
        platform=manifest.platform,
        images=tuple(images),
    )


def _require_same_environment(
    baseline: ExternalAnchorEnvironment,
    candidate: ExternalAnchorEnvironment,
) -> None:
    if baseline.fingerprint() != candidate.fingerprint():
        raise ExternalAnchorDriftError(
            "External environment drift: dataset, evaluator, platform, selection or image digest changed"
        )


def _spearman_rho(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        raise ExternalAnchorError("Spearman correlation requires equally sized score vectors")
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    mean_left = sum(left_ranks) / len(left_ranks)
    mean_right = sum(right_ranks) / len(right_ranks)
    numerator = sum(
        (left_rank - mean_left) * (right_rank - mean_right)
        for left_rank, right_rank in zip(left_ranks, right_ranks, strict=True)
    )
    left_sum = sum((value - mean_left) ** 2 for value in left_ranks)
    right_sum = sum((value - mean_right) ** 2 for value in right_ranks)
    if math.isclose(left_sum, 0.0) or math.isclose(right_sum, 0.0):
        return None
    return numerator / math.sqrt(left_sum * right_sum)


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and math.isclose(order[end][1], order[start][1], abs_tol=1e-12):
            end += 1
        rank = (start + 1 + end) / 2
        for index, _ in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _direction_agreement(left: Sequence[float], right: Sequence[float]) -> tuple[int, float | None]:
    comparable = 0
    agreements = 0
    for first in range(len(left)):
        for second in range(first + 1, len(left)):
            left_delta = left[second] - left[first]
            right_delta = right[second] - right[first]
            if math.isclose(left_delta, 0.0, abs_tol=1e-12) or math.isclose(right_delta, 0.0, abs_tol=1e-12):
                continue
            comparable += 1
            if left_delta * right_delta > 0:
                agreements += 1
    return comparable, agreements / comparable if comparable else None


def _anchor_report_markdown(report: ExternalAnchorReport) -> str:
    lines = ["# SWE-bench-Live 外部锚点报告", "", f"- 状态：`{report.status.value}`"]
    lines.append(f"- gold 稳定分母：{report.valid_denominator}")
    if report.success_rate is not None and report.success_interval is not None:
        lines.append(f"- 外部通过率：{report.success_rate:.1%} ({report.passed}/{report.valid_denominator})")
        lines.append(
            "- Wilson 95% 区间："
            f"{report.success_interval.lower:.1%}--{report.success_interval.upper:.1%}"
        )
    if report.reason:
        lines.append(f"- 原因：{report.reason}")
    lines.extend(["", "## Gold 预检", ""])
    for entry in report.gold_preflight.entries:
        lines.append(f"- `{entry.instance_id}`：{'stable' if entry.stable else 'excluded'}")
    return "\n".join(lines) + "\n"


def _controlled_reason(value: object) -> str:
    return str(value).replace("\n", " ").replace("\r", " ").strip()[:320] or "External evaluator failed"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_json(value: object) -> str:
    return _sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
