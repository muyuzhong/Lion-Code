"""Harbor v0.22.0 的单题 installed-agent 运行器。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact import CommitArtifact
from .models import (
    AdapterStatus,
    ExperimentManifest,
    FailureSource,
    HarborRoutineVerifierResult,
    TaskSpec,
    TrialExecutionStatus,
    VerifierOutcome,
    WorkerResult,
)
from .swebench_verified import parse_harbor_result
from .trace import redact_text
from .variant_injection import (
    spec_from_manifest,
)

HARBOR_VERSION = "0.22.0"
HARBOR_DATASET = "swebench-verified"
HARBOR_AGENT_IMPORT_PATH = "benchmarks.agent_e2e.harbor_agent:LionInstalledAgent"
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,239}\Z")


class HarborExecutionError(RuntimeError):
    """Harbor 版本、输入或受控结果不满足单题执行契约。"""


@dataclass(frozen=True, slots=True)
class HarborExecutionRequest:
    """一次固定 Harbor 数据集单题运行的 host 请求。"""

    repository_root: Path
    artifact: CommitArtifact
    manifest: ExperimentManifest
    task: TaskSpec
    output_dir: Path
    attempt: int = 1
    harbor_executable: str = "harbor"
    dataset: str = HARBOR_DATASET
    agent_import_path: str = HARBOR_AGENT_IMPORT_PATH
    # 注入映射表只随冻结 manifest 传递(单一事实来源);
    # request_variant=True 表示声明「这是受控实验的 run」并要求 manifest 携带映射表。
    request_variant: bool = False


@dataclass(frozen=True, slots=True)
class HarborExecutionOutput:
    """Harbor 日常摘要及给官方 Harness 使用的受控 patch。"""

    result: HarborRoutineVerifierResult
    patch_path: Path | None = None
    worker_result: WorkerResult | None = None


class HarborSingleTaskRunner:
    """以固定 argv 启动 Harbor，不在 Lion 内实现第二套容器调度器。"""

    def __init__(self, *, docker_executable: str = "docker") -> None:
        self.docker_executable = docker_executable

    def build_command(
        self,
        request: HarborExecutionRequest,
        job_root: Path,
    ) -> list[str]:
        """构造无 shell 的 Harbor 单题命令，供运行器和边界测试共同使用。"""

        repository_root = request.repository_root.resolve()
        wheel_argument = _relative_argument(
            request.artifact.wheel_path, repository_root
        )
        jobs_argument = _relative_argument(job_root, repository_root)
        return [
            request.harbor_executable,
            "run",
            "--dataset",
            request.dataset,
            "--include-task-name",
            _harbor_task_id(request.task),
            "--n-tasks",
            "1",
            "--n-attempts",
            "1",
            "--n-concurrent",
            "1",
            "--jobs-dir",
            jobs_argument,
            "--agent",
            request.agent_import_path,
            "--model",
            request.manifest.profile.model,
            "--agent-kwarg",
            f"wheel_path={wheel_argument}",
            "--agent-kwarg",
            f"manifest_json={request.manifest.canonical_json()}",
            "--agent-kwarg",
            f"task_json={request.task.canonical_json()}",
            "--agent-kwarg",
            f"attempt={request.attempt}",
            "--agent-include-logs",
            "worker-result.json",
            "--agent-include-logs",
            "trace.json",
            "--agent-include-logs",
            "lion.patch",
            "--delete",
        ]

    def run(self, request: HarborExecutionRequest) -> HarborExecutionOutput:
        """执行单题 trial，复制受控产物后清理 Harbor 原始 job 目录。"""

        validation_error = _validate_request(request)
        if validation_error is not None:
            return HarborExecutionOutput(validation_error)
        output_dir = request.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        job_root = output_dir / ".harbor-run" / request.manifest.run_id
        if job_root.exists():
            return HarborExecutionOutput(
                _unavailable(
                    request,
                    status=AdapterStatus.INVALID,
                    execution_status=TrialExecutionStatus.INFRA_FAILED,
                    failure_source=FailureSource.PATH,
                    reason="Harbor run directory already exists",
                )
            )
        result: HarborExecutionOutput | None = None
        cleanup_failed = False
        try:
            try:
                preflight = self._preflight(request)
                if preflight is not None:
                    result = HarborExecutionOutput(preflight)
                else:
                    job_root.parent.mkdir(parents=True, exist_ok=True)
                    process = _run_harbor(
                        self.build_command(request, job_root), request, job_root
                    )
                    if process.timed_out:
                        result = HarborExecutionOutput(
                            _unavailable(
                                request,
                                status=AdapterStatus.TIMEOUT,
                                execution_status=TrialExecutionStatus.INDETERMINATE,
                                failure_source=FailureSource.TIMEOUT,
                                reason="Harbor trial timed out",
                            )
                        )
                    else:
                        result_path = _find_trial_result(
                            job_root, _harbor_task_id(request.task)
                        )
                        if result_path is None:
                            result = HarborExecutionOutput(
                                _unavailable(
                                    request,
                                    status=AdapterStatus.UNAVAILABLE,
                                    execution_status=TrialExecutionStatus.INFRA_FAILED,
                                    failure_source=FailureSource.HARBOR,
                                    reason=(
                                        "Harbor process failed"
                                        if process.returncode != 0
                                        else "Harbor trial result is missing"
                                    ),
                                )
                            )
                        else:
                            result = _read_trial_output(request, job_root, result_path)
            except Exception as error:
                reason, _ = redact_text(
                    str(error) or "Invalid Harbor trial result", max_length=320
                )
                result = HarborExecutionOutput(
                    _unavailable(
                        request,
                        status=AdapterStatus.INVALID,
                        execution_status=TrialExecutionStatus.INFRA_FAILED,
                        failure_source=FailureSource.SCHEMA,
                        reason=reason,
                    )
                )
        finally:
            cleanup_failed = _cleanup_job_root(job_root)
        if cleanup_failed:
            return HarborExecutionOutput(
                _unavailable(
                    request,
                    status=AdapterStatus.INVALID,
                    execution_status=TrialExecutionStatus.INDETERMINATE,
                    failure_source=FailureSource.CLEANUP,
                    reason="Harbor artifact cleanup failed",
                )
            )
        if result is None:
            raise HarborExecutionError("Harbor runner produced no result")
        return result

    def _preflight(
        self,
        request: HarborExecutionRequest,
    ) -> HarborRoutineVerifierResult | None:
        if platform.system() != "Linux":
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.DOCKER,
                reason="Harbor Verified execution requires Linux",
            )
        if shutil.which(request.harbor_executable) is None:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.HARBOR,
                reason="Harbor executable is unavailable",
            )
        version = _harbor_version(request.harbor_executable)
        if version != HARBOR_VERSION:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.HARBOR,
                reason=f"Harbor version is not pinned to {HARBOR_VERSION}",
            )
        if shutil.which(self.docker_executable) is None:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.DOCKER,
                reason="Docker executable is unavailable",
            )
        docker = subprocess.run(
            [self.docker_executable, "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
        if docker.returncode != 0:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.DOCKER,
                reason="Docker daemon is unavailable",
            )
        missing_credentials = tuple(
            name
            for name in request.manifest.profile.credential_env_vars
            if not os.environ.get(name)
        )
        if missing_credentials:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.HARBOR,
                reason="Required provider credentials are unavailable",
            )
        return None


@dataclass(frozen=True, slots=True)
class _HarborProcess:
    returncode: int
    timed_out: bool = False


def _run_harbor(
    command: list[str],
    request: HarborExecutionRequest,
    job_root: Path,
) -> _HarborProcess:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    pythonpath = str(request.repository_root.resolve())
    if existing_pythonpath:
        pythonpath = os.pathsep.join((pythonpath, existing_pythonpath))
    environment["PYTHONPATH"] = pythonpath
    try:
        process = subprocess.run(
            command,
            cwd=request.repository_root.resolve(),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=max(1, math.ceil(request.manifest.timeout_seconds)) + 180,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return _HarborProcess(returncode=124, timed_out=True)
    except OSError as error:
        raise HarborExecutionError("Unable to start Harbor") from error
    return _HarborProcess(returncode=process.returncode)


def _read_trial_output(
    request: HarborExecutionRequest,
    job_root: Path,
    result_path: Path,
) -> HarborExecutionOutput:
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise HarborExecutionError("Harbor trial result must be an object")
    trial_task = raw.get("task_name")
    if trial_task != _harbor_task_id(request.task):
        raise HarborExecutionError("Harbor trial task_name does not match request")
    trial_root = result_path.parent
    patch_source = _find_named_file(trial_root, "lion.patch")
    worker_source = _find_named_file(trial_root, "worker-result.json")
    trace_source = _find_named_file(trial_root, "trace.json")
    controlled_root = request.output_dir.resolve() / "artifacts"
    controlled_root.mkdir(parents=True, exist_ok=True)
    patch_path = _copy_controlled(patch_source, controlled_root / "harbor-patch.diff")
    worker_path = _copy_controlled(
        worker_source,
        controlled_root / "harbor-worker-result.json",
    )
    trace_path = _copy_controlled(trace_source, controlled_root / "harbor-trace.json")
    worker_result = None
    if worker_path is not None:
        worker_result = WorkerResult.from_json(worker_path.read_text(encoding="utf-8"))

    raw_digest = _sha256_text(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    verifier = raw.get("verifier_result")
    reward = _reward_from_verifier(verifier)
    exception = raw.get("exception_info")
    status = _raw_status(reward, exception)
    failure_source = _raw_failure_source(status, exception)
    reason = _raw_reason(status, exception)
    artifact_paths = tuple(
        path.relative_to(request.output_dir.resolve()).as_posix()
        for path in (worker_path, trace_path)
        if path is not None
    )
    fixture: dict[str, Any] = {
        "schema_version": "harbor-result/v1",
        "task_id": request.task.task_id,
        "job_id": _job_id(raw, job_root),
        "status": status,
        "reward": reward,
        "verifier_outcome": (
            VerifierOutcome.PASSED.value
            if reward is not None and reward >= 1
            else VerifierOutcome.FAILED.value
            if reward is not None
            else None
        ),
        "patch_path": (
            patch_path.relative_to(request.output_dir.resolve()).as_posix()
            if patch_path is not None
            else None
        ),
        "artifact_paths": artifact_paths,
        "output": f"harbor_result_digest={raw_digest}",
        "command_summary": f"Harbor {HARBOR_VERSION} single-task trial",
        "error": reason,
        "failure_source": failure_source,
    }
    routine = parse_harbor_result(
        fixture,
        job_root=request.output_dir.resolve(),
        expected_task_id=request.task.task_id,
    )
    routine = routine.model_copy(update={"output_digest": raw_digest})
    return HarborExecutionOutput(routine, patch_path, worker_result)


def _find_trial_result(job_root: Path, task_id: str) -> Path | None:
    candidates: list[Path] = []
    for path in job_root.rglob("result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping) and payload.get("task_name") == task_id:
            candidates.append(path)
    if len(candidates) > 1:
        raise HarborExecutionError("Multiple Harbor trial results matched the task")
    return candidates[0] if candidates else None


def _find_named_file(root: Path, filename: str) -> Path | None:
    candidates = sorted(path for path in root.rglob(filename) if path.is_file())
    if len(candidates) > 1:
        raise HarborExecutionError(f"Multiple Harbor artifacts named {filename}")
    return candidates[0] if candidates else None


def _copy_controlled(source: Path | None, destination: Path) -> Path | None:
    if source is None:
        return None
    shutil.copy2(source, destination)
    return destination


def _cleanup_job_root(job_root: Path) -> bool:
    try:
        if job_root.exists():
            shutil.rmtree(job_root)
        parent = job_root.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        return True
    return False


def _reward_from_verifier(value: Any) -> float | None:
    if not isinstance(value, Mapping):
        return None
    rewards = value.get("rewards")
    if not isinstance(rewards, Mapping):
        return None
    selected: Any = rewards.get("reward")
    if selected is None:
        selected = rewards.get("resolved")
    if selected is None and len(rewards) == 1:
        selected = next(iter(rewards.values()))
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        return None
    if not 0 <= float(selected) <= 1:
        return None
    return float(selected)


def _raw_status(reward: float | None, exception: Any) -> str:
    if isinstance(exception, Mapping):
        exception_type = str(exception.get("exception_type", "")).casefold()
        if "timeout" in exception_type:
            return "timeout"
        if "cancel" in exception_type or "interrupt" in exception_type:
            return "cancelled"
        if any(part in exception_type for part in ("docker", "image", "environment")):
            return "docker_error"
        return "agent_error"
    return "completed" if reward is not None else "schema_error"


def _raw_failure_source(status: str, exception: Any) -> str | None:
    if status == "timeout":
        return FailureSource.TIMEOUT.value
    if status == "cancelled":
        return FailureSource.CANCELLATION.value
    if status == "docker_error":
        return FailureSource.DOCKER.value
    if status == "agent_error":
        return FailureSource.HARBOR.value
    if status == "schema_error":
        return FailureSource.SCHEMA.value
    return None


def _raw_reason(status: str, exception: Any) -> str | None:
    if status == "completed":
        return None
    if isinstance(exception, Mapping):
        exception_type = str(exception.get("exception_type", "Harbor error"))
        if not _SAFE_COMPONENT.fullmatch(exception_type):
            exception_type = "unrecognized"
        return f"Harbor trial error: {exception_type}"[:320]
    return "Harbor trial result is missing a scalar reward"


def _job_id(raw: Mapping[str, Any], job_root: Path) -> str:
    for key in ("trial_name", "id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if _SAFE_COMPONENT.fullmatch(value):
                return value
            return f"trial-{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
    return job_root.name


def _harbor_task_id(task: TaskSpec) -> str:
    value = task.extensions.get("harbor_task_name", task.task_id)
    if not isinstance(value, str) or not _SAFE_COMPONENT.fullmatch(value):
        raise HarborExecutionError("Harbor task name is invalid")
    return value


def _harbor_version(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"(?<!\d)\d+\.\d+\.\d+(?!\d)", result.stdout)
    return match.group(0) if match else None


def _relative_argument(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def _validate_request(
    request: HarborExecutionRequest,
) -> HarborRoutineVerifierResult | None:
    if not _SAFE_COMPONENT.fullmatch(request.manifest.run_id):
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            execution_status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.PATH,
            reason="Harbor run_id is invalid",
        )
    if request.dataset != HARBOR_DATASET:
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            execution_status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.SCHEMA,
            reason="Only the pinned Harbor SWE-bench Verified dataset is supported",
        )
    if request.agent_import_path != HARBOR_AGENT_IMPORT_PATH:
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            execution_status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.SCHEMA,
            reason="Only the pinned Lion installed-agent is supported",
        )
    if request.attempt < 1:
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            execution_status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.SCHEMA,
            reason="Harbor attempt must be positive",
        )
    if not request.artifact.wheel_path.is_file():
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            execution_status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.PATH,
            reason="Lion wheel artifact is missing",
        )
    if request.task.task_id not in request.manifest.task_ids:
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            execution_status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.SCHEMA,
            reason="Harbor task is not selected by manifest",
        )
    if request.request_variant:
        # 映射表只从 manifest 读取:worker 端同样以 manifest 为唯一来源,
        # 双数据源会让「请求的 spec」与「执行的 spec」可能不一致。
        if spec_from_manifest(request.manifest) is None:
            return _unavailable(
                request,
                status=AdapterStatus.INVALID,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                failure_source=FailureSource.SCHEMA,
                reason="Variant experiment manifest must carry the injection spec",
            )
    return None


def _unavailable(
    request: HarborExecutionRequest,
    *,
    status: AdapterStatus,
    execution_status: TrialExecutionStatus,
    failure_source: FailureSource,
    reason: str,
) -> HarborRoutineVerifierResult:
    return HarborRoutineVerifierResult(
        task_id=request.task.task_id,
        job_id="unavailable",
        status=status,
        execution_status=execution_status,
        failure_source=failure_source,
        reason=reason[:320],
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "HARBOR_AGENT_IMPORT_PATH",
    "HARBOR_DATASET",
    "HARBOR_VERSION",
    "HarborExecutionError",
    "HarborExecutionOutput",
    "HarborExecutionRequest",
    "HarborSingleTaskRunner",
]
