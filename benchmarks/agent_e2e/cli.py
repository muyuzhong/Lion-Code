"""离线评测 CLI；真实容器运行仍必须通过显式的官方 runner。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .backend import unavailable_backend_for_host
from .catalog import load_catalog, load_catalog_lock, validate_catalog
from .checkpoint import JsonCheckpointStore
from .external_anchor import validate_bundled_external_anchor_manifest
from .models import ExperimentManifest
from .orchestrator import SingleTaskOrchestrator
from .report import build_report, write_report
from .verified_runner import (
    VerifiedExecutionRequest,
    run_verified_evaluation,
    verified_exit_code,
    write_verified_report,
)


def build_parser() -> argparse.ArgumentParser:
    """构造无网络、副作用受控的评测命令行。"""

    parser = argparse.ArgumentParser(prog="python -m benchmarks.agent_e2e")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="校验公开 catalog 与冻结 lock")
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--lock", type=Path, required=True)

    offline = commands.add_parser(
        "offline-run",
        help="仅执行 manifest/catalog/checkpoint 验证并输出 blocked 证据",
    )
    offline.add_argument("--catalog", type=Path, required=True)
    offline.add_argument("--manifest", type=Path, required=True)
    offline.add_argument("--task-id", required=True)
    offline.add_argument("--attempt", type=int, default=1)
    offline.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/agent_e2e/results"),
    )

    online = commands.add_parser(
        "online-run",
        help="预留的真实容器入口；foundation 阶段始终 blocked",
    )
    online.add_argument("--manifest", type=Path, required=True)

    verified = commands.add_parser(
        "verified-run",
        help="运行单题 Harbor installed-agent 与官方 SWE-bench Harness",
    )
    verified.add_argument("--catalog", type=Path, required=True)
    verified.add_argument("--manifest", type=Path, required=True)
    verified.add_argument("--task-id", required=True)
    verified.add_argument("--commit", required=True)
    verified.add_argument(
        "--run-id",
        help="可选的运行 ID 校验；默认使用 manifest.run_id",
    )
    verified.add_argument("--repository-root", type=Path, default=Path("."))
    verified.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/agent_e2e/results/verified"),
    )
    verified.add_argument("--python", dest="python_executable", default=sys.executable)
    verified.add_argument("--harness-python", default=sys.executable)
    verified.add_argument("--harbor", default="harbor")
    verified.add_argument("--input-digest")
    verified.add_argument("--deepeval-judge-model")
    verified.add_argument("--deepeval-timeout", type=float, default=120.0)
    verified.add_argument("--opik-timeout", type=float, default=30.0)
    verified.add_argument("--opik-project")
    verified.add_argument("--opik-workspace")

    anchor_validate = commands.add_parser(
        "external-anchor-validate",
        help="校验仓库内冻结的 SWE-bench-Live 外部锚点清单，不访问网络或 Docker",
    )
    anchor_validate.add_argument(
        "--show-instance-ids",
        action="store_true",
        help="在受控 JSON 中输出冻结的 20 个 instance ID",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行 CLI，不读取凭证值、不探测 Docker、不发起提供商请求。"""

    args = build_parser().parse_args(argv)
    if args.command == "validate":
        catalog = load_catalog(args.catalog)
        lock = load_catalog_lock(args.lock)
        validation = validate_catalog(catalog, lock=lock)
        print(
            json.dumps(
                {
                    "status": "valid",
                    "catalog_sha256": validation.catalog_sha256,
                    "task_count": validation.task_count,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "offline-run":
        return asyncio.run(_offline_run(args))
    if args.command == "online-run":
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "Real Docker/provider execution is disabled in the evaluation foundation",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if args.command == "verified-run":
        return _verified_run(args)
    if args.command == "external-anchor-validate":
        manifest = validate_bundled_external_anchor_manifest()
        payload = {
            "status": "valid",
            "anchor_id": manifest.anchor_id,
            "manifest_fingerprint": manifest.fingerprint(),
            "dataset_revision": manifest.dataset_revision,
            "evaluator_revision": manifest.evaluator_revision,
            "instance_count": len(manifest.instances),
        }
        if args.show_instance_ids:
            payload["instance_ids"] = manifest.instance_ids
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


async def _offline_run(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.catalog)
    manifest = ExperimentManifest.from_json(args.manifest.read_text(encoding="utf-8"))
    validate_catalog(catalog, lock=manifest.catalog)
    task = next((item for item in catalog.tasks if item.task_id == args.task_id), None)
    if task is None:
        raise ValueError(f"Unknown task_id: {args.task_id}")
    output_dir = args.output_dir
    orchestrator = SingleTaskOrchestrator(
        backend=unavailable_backend_for_host(),
        checkpoint_store=JsonCheckpointStore(output_dir / "checkpoints"),
        work_root=output_dir / "work",
    )
    result = await orchestrator.run_task(
        manifest=manifest,
        task=task,
        attempt=args.attempt,
    )
    report = build_report(manifest=manifest, results=[result])
    json_path, markdown_path = write_report(report, output_dir=output_dir)
    print(
        json.dumps(
            {
                "status": result.verdict.value,
                "report_json": str(json_path),
                "report_markdown": str(markdown_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _verified_run(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.catalog)
    manifest = ExperimentManifest.from_json(args.manifest.read_text(encoding="utf-8"))
    if args.run_id is not None and args.run_id != manifest.run_id:
        raise ValueError("--run-id must match manifest.run_id")
    validate_catalog(catalog, lock=manifest.catalog)
    task = next((item for item in catalog.tasks if item.task_id == args.task_id), None)
    if task is None:
        raise ValueError(f"Unknown task_id: {args.task_id}")
    execution = run_verified_evaluation(
        VerifiedExecutionRequest(
            repository_root=args.repository_root,
            commit_sha=args.commit,
            manifest=manifest,
            task=task,
            output_dir=args.output_dir,
            python_executable=args.python_executable,
            harness_python=args.harness_python,
            harbor_executable=args.harbor,
            input_digest=args.input_digest,
            deepeval_judge_model=args.deepeval_judge_model,
            deepeval_timeout_seconds=args.deepeval_timeout,
            opik_timeout_seconds=args.opik_timeout,
            opik_project_name=args.opik_project,
            opik_workspace=args.opik_workspace,
        )
    )
    json_path, markdown_path = write_verified_report(
        execution.report,
        args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": (
                    execution.report.trial.status.value
                    if execution.report.trial is not None
                    else "infra_failed"
                ),
                "verdict": execution.report.task_result.verdict.value,
                "report_json": str(json_path),
                "report_markdown": str(markdown_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return verified_exit_code(execution.report)
