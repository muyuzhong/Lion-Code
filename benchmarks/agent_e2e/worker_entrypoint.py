"""Harbor 容器内的最小 worker 入口与 patch 导出器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .agent_worker import run_agent_worker
from .backend import AgentExecutionRequest
from .evidence import ProcessEvidenceProjector
from .models import WorkerResult, WorkerStatus
from .trace import TraceRecorder, redact_text
from .variant_injection import spec_from_manifest

REQUEST_PATH = Path("/installed-agent/request.json")
LOG_ROOT = Path("/logs/agent")
PATCH_PATH = LOG_ROOT / "lion.patch"
RESULT_PATH = LOG_ROOT / "worker-result.json"
TRACE_PATH = LOG_ROOT / "trace.json"


def main() -> int:
    """运行现有 Lion worker，并只写入受控结果、轨迹和 patch。"""

    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Worker request must be a JSON object")
    manifest_payload = payload.get("manifest")
    task_payload = payload.get("task")
    if not isinstance(manifest_payload, Mapping) or not isinstance(
        task_payload, Mapping
    ):
        raise ValueError("Worker request is missing manifest or task")
    from .models import ExperimentManifest, TaskSpec

    manifest = ExperimentManifest.from_dict(manifest_payload)
    task = TaskSpec.from_dict(task_payload)
    request = AgentExecutionRequest(
        manifest=manifest,
        task=task,
        attempt=int(payload.get("attempt", 1)),
        agent_workspace=Path.cwd(),
        session_root=Path("/tmp/lion-e2e-sessions"),
    )
    recorder = TraceRecorder(
        projector=ProcessEvidenceProjector(
            validation_commands=task.public_validation_commands,
        )
    )
    injection_spec = spec_from_manifest(manifest)
    result = asyncio.run(
        run_agent_worker(
            request,
            trace_recorder=recorder,
            injection_spec=injection_spec,
        )
    )
    try:
        # 以任务卡片的 base_revision 为 diff 基准:兼容 Agent 既未提交
        # 又已自行 git commit 的两种改动形态(官方 Harness 在 base 上应用 patch)。
        base_revision = task.base_revision
        patch_sha256, patch_applied = export_git_patch(
            Path.cwd(), PATCH_PATH, base_revision=base_revision
        )
        result = result.model_copy(
            update={
                "patch_sha256": patch_sha256,
                "patch_applied": patch_applied,
            }
        )
    except Exception as error:
        summary, _ = redact_text(str(error) or error.__class__.__name__, max_length=320)
        result = WorkerResult(
            status=WorkerStatus.ERROR,
            agent_run=result.agent_run,
            trace_summary=result.trace_summary,
            error_summary=f"patch export failed: {summary}",
        )
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(result.canonical_json() + "\n", encoding="utf-8")
    recorder.write_json(TRACE_PATH)
    return 0


def export_git_patch(
    workspace: str | Path,
    destination: str | Path,
    *,
    base_revision: str | None = None,
) -> tuple[str | None, bool]:
    """导出 tracked 与 untracked 改动，不把评测输出目录纳入 patch。"""

    root = Path(workspace).resolve()
    destination_path = Path(destination).resolve()
    tracked = _git_bytes(
        root,
        "diff",
        base_revision or "HEAD",
        "--binary",
        "--no-ext-diff",
    )
    excluded_prefix: Path | None = None
    try:
        destination_path.relative_to(root)
        excluded_prefix = destination_path.parent.relative_to(root)
        if excluded_prefix == Path("."):
            excluded_prefix = destination_path.relative_to(root)
    except ValueError:
        pass
    untracked = _untracked_files(root, excluded_prefix=excluded_prefix)
    chunks = [tracked] if tracked else []
    for relative in untracked:
        diff = _git_bytes(
            root,
            "diff",
            "--no-index",
            "--binary",
            "--",
            "/dev/null",
            relative,
            allow_difference=True,
        )
        if diff:
            if chunks and not chunks[-1].endswith(b"\n"):
                chunks.append(b"\n")
            chunks.append(diff)
    patch = b"".join(chunks)
    if not patch:
        if destination_path.exists():
            destination_path.unlink()
        return None, False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(patch)
    return hashlib.sha256(patch).hexdigest(), True


def _untracked_files(
    root: Path, *, excluded_prefix: Path | None = None
) -> tuple[str, ...]:
    listing = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z")
    files: list[str] = []
    for raw_name in listing.split(b"\0"):
        if not raw_name:
            continue
        name = os.fsdecode(raw_name)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Git returned an unsafe untracked path")
        if excluded_prefix is not None and (
            path == excluded_prefix or excluded_prefix in path.parents
        ):
            continue
        files.append(path.as_posix())
    return tuple(sorted(files))


def _git_bytes(
    root: Path,
    *arguments: str,
    allow_difference: bool = False,
) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    allowed = {0, 1} if allow_difference else {0}
    if result.returncode not in allowed:
        raise RuntimeError("Git could not export the workspace patch")
    return result.stdout


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["export_git_patch", "main"]
