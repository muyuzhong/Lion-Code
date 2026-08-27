"""固定 SWE-bench Harness 版本的单题官方复核入口。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .harness import parse_harness_result
from .models import (
    AdapterStatus,
    FailureSource,
    HarnessRecheckResult,
)
from .trace import redact_text

SWEBENCH_VERSION = "5.0.1"
SWEBENCH_DATASET = "SWE-bench/SWE-bench_Verified"
SWEBENCH_SPLIT = "test"
SWEBENCH_HARNESS_MODULE = "swebench.harness.run_evaluation"
SWEBENCH_EVALUATOR_REVISION = f"swebench-{SWEBENCH_VERSION}"
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+@-]{0,255}\Z")


class HarnessExecutionError(RuntimeError):
    """官方 Harness 输入、版本或受控输出不满足执行契约。"""


@dataclass(frozen=True, slots=True)
class HarnessExecutionRequest:
    """一次只复核一个 instance 的官方 Harness 请求。"""

    instance_id: str
    patch_path: Path
    patch_sha256: str
    model_name: str
    run_id: str
    output_dir: Path
    timeout_seconds: float
    image_digest: str | None
    python_executable: str | Path = sys.executable
    dataset_name: str = SWEBENCH_DATASET
    split: str = SWEBENCH_SPLIT


@dataclass(frozen=True, slots=True)
class HarnessExecutionOutput:
    """官方复核摘要与保留的 prediction JSONL。"""

    result: HarnessRecheckResult
    prediction_path: Path | None = None


class OfficialSWEbenchHarnessRunner:
    """调用固定版本的官方 Harness，不复制或改写 verifier。"""

    def __init__(self, *, docker_executable: str = "docker") -> None:
        self.docker_executable = docker_executable

    def run(self, request: HarnessExecutionRequest) -> HarnessExecutionOutput:
        """写入标准 prediction、执行单题 Harness 并清理原始日志目录。"""

        validation_error = _validate_request(request)
        if validation_error is not None:
            return HarnessExecutionOutput(validation_error)
        output_dir = request.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        work_root = output_dir / ".harness-run" / request.run_id
        if work_root.exists():
            return HarnessExecutionOutput(
                _unavailable(
                    request,
                    status=AdapterStatus.INVALID,
                    failure_source=FailureSource.PATH,
                    reason="Harness run directory already exists",
                )
            )
        prediction_path = work_root / "predictions.jsonl"
        controlled_prediction = output_dir / "artifacts" / "harness-predictions.jsonl"
        result: HarnessExecutionOutput | None = None
        cleanup_failed = False
        try:
            try:
                work_root.mkdir(parents=True)
                _write_prediction(request, prediction_path)
                controlled_prediction.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(prediction_path, controlled_prediction)

                unavailable = self._preflight(request)
                if unavailable is not None:
                    result = HarnessExecutionOutput(unavailable, controlled_prediction)
                else:
                    process = _run_harness(request, work_root)
                    if process.returncode != 0:
                        result = HarnessExecutionOutput(
                            _unavailable(
                                request,
                                status=(
                                    AdapterStatus.TIMEOUT
                                    if process.timed_out
                                    else AdapterStatus.UNAVAILABLE
                                ),
                                failure_source=(
                                    FailureSource.TIMEOUT
                                    if process.timed_out
                                    else FailureSource.HARNESS
                                ),
                                reason=(
                                    "Official Harness evaluation timed out"
                                    if process.timed_out
                                    else "Official Harness process failed"
                                ),
                            ),
                            controlled_prediction,
                        )
                    else:
                        report_path = _instance_report_path(request, work_root)
                        if not report_path.is_file():
                            result = HarnessExecutionOutput(
                                _unavailable(
                                    request,
                                    status=AdapterStatus.UNAVAILABLE,
                                    failure_source=FailureSource.HARNESS,
                                    reason="Official Harness report is missing",
                                ),
                                controlled_prediction,
                            )
                        else:
                            result = HarnessExecutionOutput(
                                _parse_official_report(request, report_path),
                                controlled_prediction,
                            )
            except Exception as error:
                reason, _ = redact_text(
                    str(error) or "Invalid Harness execution input", max_length=320
                )
                result = HarnessExecutionOutput(
                    _unavailable(
                        request,
                        status=AdapterStatus.INVALID,
                        failure_source=FailureSource.SCHEMA,
                        reason=reason,
                    ),
                    controlled_prediction if controlled_prediction.exists() else None,
                )
        finally:
            cleanup_failed = _cleanup_run_root(work_root)
        if cleanup_failed:
            return HarnessExecutionOutput(
                _unavailable(
                    request,
                    status=AdapterStatus.INVALID,
                    failure_source=FailureSource.CLEANUP,
                    reason="Official Harness artifact cleanup failed",
                ),
                controlled_prediction if controlled_prediction.exists() else None,
            )
        if result is None:
            raise HarnessExecutionError("Harness runner produced no result")
        return result

    def _preflight(
        self,
        request: HarnessExecutionRequest,
    ) -> HarnessRecheckResult | None:
        if platform.system() != "Linux":
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                failure_source=FailureSource.DOCKER,
                reason="Official SWE-bench Harness requires Linux",
            )
        version = _package_version(request.python_executable)
        if version != SWEBENCH_VERSION:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
                failure_source=FailureSource.HARNESS,
                reason=f"SWE-bench version is not pinned to {SWEBENCH_VERSION}",
            )
        if request.image_digest is None:
            return _unavailable(
                request,
                status=AdapterStatus.INVALID,
                failure_source=FailureSource.SCHEMA,
                reason="Manifest is missing the verifier image digest",
            )
        if shutil.which(self.docker_executable) is None:
            return _unavailable(
                request,
                status=AdapterStatus.UNAVAILABLE,
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
                failure_source=FailureSource.DOCKER,
                reason="Docker daemon is unavailable",
            )
        return None


@dataclass(frozen=True, slots=True)
class _HarnessProcess:
    returncode: int
    timed_out: bool = False


def _run_harness(
    request: HarnessExecutionRequest,
    work_root: Path,
) -> _HarnessProcess:
    command = [
        str(request.python_executable),
        "-m",
        SWEBENCH_HARNESS_MODULE,
        "--dataset_name",
        request.dataset_name,
        "--split",
        request.split,
        "--instance_ids",
        request.instance_id,
        "--predictions_path",
        "predictions.jsonl",
        "--max_workers",
        "1",
        "--run_id",
        request.run_id,
        "--timeout",
        str(max(1, math.ceil(request.timeout_seconds))),
        "--report_dir",
        "reports",
    ]
    try:
        process = subprocess.run(
            command,
            cwd=work_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=max(1, math.ceil(request.timeout_seconds)) + 60,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    except subprocess.TimeoutExpired:
        return _HarnessProcess(returncode=124, timed_out=True)
    except OSError as error:
        raise HarnessExecutionError("Unable to start the official Harness") from error
    return _HarnessProcess(returncode=process.returncode)


def _parse_official_report(
    request: HarnessExecutionRequest,
    report_path: Path,
) -> HarnessRecheckResult:
    report_text = report_path.read_text(encoding="utf-8", errors="replace")
    output_digest = _sha256_text(report_text)
    try:
        payload = json.loads(report_text)
    except json.JSONDecodeError:
        return _invalid_report(
            request, output_digest, "Official Harness report is not JSON"
        )
    if not isinstance(payload, Mapping):
        return _invalid_report(
            request, output_digest, "Official Harness report is not an object"
        )
    instance = payload.get(request.instance_id)
    if not isinstance(instance, Mapping) or not isinstance(
        instance.get("resolved"), bool
    ):
        return _invalid_report(
            request,
            output_digest,
            "Official Harness report has no boolean resolved field",
        )
    fixture_report = (
        report_text
        if len(report_text) <= 100_000
        else (f"report_digest={output_digest}")
    )
    result = parse_harness_result(
        {
            "schema_version": "swebench-harness-result/v1",
            "instance_id": request.instance_id,
            "status": "completed",
            "resolved": instance["resolved"],
            "report": fixture_report,
            "evaluator_revision": SWEBENCH_EVALUATOR_REVISION,
            "image_digest": request.image_digest,
        },
        expected_task_id=request.instance_id,
        patch_sha256=request.patch_sha256,
    )
    if result.output_digest != output_digest:
        result = result.model_copy(update={"output_digest": output_digest})
    return result


def _instance_report_path(
    request: HarnessExecutionRequest,
    work_root: Path,
) -> Path:
    model_directory = request.model_name.replace("/", "__")
    return (
        work_root
        / "logs"
        / "run_evaluation"
        / request.run_id
        / model_directory
        / request.instance_id
        / "report.json"
    )


def _cleanup_run_root(work_root: Path) -> bool:
    try:
        if work_root.exists():
            shutil.rmtree(work_root)
        parent = work_root.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        return True
    return False


def _write_prediction(request: HarnessExecutionRequest, destination: Path) -> None:
    patch_bytes = request.patch_path.read_bytes()
    observed = hashlib.sha256(patch_bytes).hexdigest()
    if observed != request.patch_sha256:
        raise HarnessExecutionError("Patch digest does not match prediction input")
    patch = patch_bytes.decode("utf-8")
    prediction = {
        "instance_id": request.instance_id,
        "model_name_or_path": request.model_name,
        "model_patch": patch,
    }
    destination.write_text(
        json.dumps(prediction, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_request(
    request: HarnessExecutionRequest,
) -> HarnessRecheckResult | None:
    model_directory = request.model_name.replace("/", "__")
    if not _SAFE_COMPONENT.fullmatch(request.instance_id):
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            failure_source=FailureSource.PATH,
            reason="Harness instance_id must be a single safe path component",
        )
    if not _SAFE_COMPONENT.fullmatch(request.run_id):
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            failure_source=FailureSource.PATH,
            reason="Harness run_id must be a single safe path component",
        )
    if not _SAFE_COMPONENT.fullmatch(model_directory):
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            failure_source=FailureSource.SCHEMA,
            reason="Harness model name is invalid",
        )
    if request.dataset_name != SWEBENCH_DATASET or request.split != SWEBENCH_SPLIT:
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            failure_source=FailureSource.SCHEMA,
            reason="Only the pinned SWE-bench Verified dataset is supported",
        )
    if request.timeout_seconds <= 0:
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            failure_source=FailureSource.SCHEMA,
            reason="Harness timeout must be positive",
        )
    if not request.patch_path.is_file():
        return _unavailable(
            request,
            status=AdapterStatus.INVALID,
            failure_source=FailureSource.PATH,
            reason="Harness patch artifact is missing",
        )
    return None


def _package_version(python_executable: str | Path) -> str | None:
    try:
        result = subprocess.run(
            [
                str(python_executable),
                "-c",
                "import importlib.metadata as m; print(m.version('swebench'))",
            ],
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
    return result.stdout.strip()


def _invalid_report(
    request: HarnessExecutionRequest,
    output_digest: str,
    reason: str,
) -> HarnessRecheckResult:
    return HarnessRecheckResult(
        task_id=request.instance_id,
        status=AdapterStatus.INVALID,
        patch_sha256=request.patch_sha256,
        output_digest=output_digest,
        evaluator_revision=SWEBENCH_EVALUATOR_REVISION,
        image_digest=request.image_digest,
        failure_source=FailureSource.SCHEMA,
        reason=reason,
    )


def _unavailable(
    request: HarnessExecutionRequest,
    *,
    status: AdapterStatus,
    failure_source: FailureSource,
    reason: str,
) -> HarnessRecheckResult:
    return HarnessRecheckResult(
        task_id=request.instance_id,
        status=status,
        patch_sha256=request.patch_sha256,
        output_digest=_sha256_text(reason),
        evaluator_revision=SWEBENCH_EVALUATOR_REVISION,
        image_digest=request.image_digest,
        failure_source=failure_source,
        reason=reason[:320],
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "SWEBENCH_DATASET",
    "SWEBENCH_EVALUATOR_REVISION",
    "SWEBENCH_HARNESS_MODULE",
    "SWEBENCH_SPLIT",
    "SWEBENCH_VERSION",
    "HarnessExecutionError",
    "HarnessExecutionOutput",
    "HarnessExecutionRequest",
    "OfficialSWEbenchHarnessRunner",
]
