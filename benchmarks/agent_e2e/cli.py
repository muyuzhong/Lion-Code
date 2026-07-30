"""离线评测 CLI；online/Docker 命令在 foundation 阶段明确拒绝执行。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from .backend import unavailable_backend_for_host
from .catalog import load_catalog, load_catalog_lock, validate_catalog
from .checkpoint import JsonCheckpointStore
from .models import ExperimentManifest
from .orchestrator import SingleTaskOrchestrator
from .report import build_report, write_report


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
