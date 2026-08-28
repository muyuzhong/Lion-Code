"""生成冻结 ExperimentManifest(单任务、repeats=1、正预算)。

凭证只以环境变量名出现在 manifest;值绝不落盘。用法:
  python build_manifest.py --model <model> --provider <provider> \\
      --env OPENAI_API_KEY,OPENAI_BASE_URL --run-id <run-id> \\
      [--task-id <id>] [--output-dir <dir>] [--budget 2.0] [--timeout 1200] \\
      [--commit <sha>]

--task-id 缺省为 catalog 中第一个任务。--output-dir 缺省为脚本自身目录,
内含 catalog.json/catalog.lock.json,manifest 亦写入该目录。
模型名优先级:--model > 环境变量 LION_MODEL。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from benchmarks.agent_e2e.catalog import catalog_sha256, load_catalog, load_catalog_lock
from benchmarks.agent_e2e.models import (
    CatalogLock,
    ExperimentManifest,
    ExperimentProfile,
)

HEAD = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=Path.cwd(), text=True
).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default="openai-compatible")
    parser.add_argument(
        "--env", required=True, help="逗号分隔的 credential_env_vars 名"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default=None, help="缺省取 catalog 第一个任务")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--budget", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--commit", default=HEAD)
    args = parser.parse_args()
    model = args.model or os.environ.get("LION_MODEL", "").strip() or None
    if not model:
        raise SystemExit("未填写模型名:请用 --model 传入,或设置环境变量 LION_MODEL")

    output_dir = Path(args.output_dir)
    catalog = load_catalog(output_dir / "catalog.json")
    lock = load_catalog_lock(output_dir / "catalog.lock.json")
    if not isinstance(lock, CatalogLock):
        raise SystemExit("catalog lock must be CatalogLock")
    if lock.catalog_sha256 != catalog_sha256(catalog):
        raise SystemExit("catalog/lock mismatch")
    task_ids = tuple(task.task_id for task in catalog.tasks)
    selected = args.task_id or task_ids[0]
    if selected not in task_ids:
        raise SystemExit(f"task-id {selected!r} 不在 catalog 任务列表中: {task_ids!r}")
    task = next(task for task in catalog.tasks if task.task_id == selected)
    credential_env_vars = tuple(
        name.strip() for name in args.env.split(",") if name.strip()
    )
    profile = ExperimentProfile(
        profile_id="verified-smoke",
        model=model,
        provider=args.provider,
        prompt_version="smoke-prompts-v1",
        compression_version="smoke-compression-v1",
        tool_policy_version="smoke-tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=args.timeout,
        budget_usd=args.budget,
        max_turns=60,
        agent_code_sha=args.commit,
        credential_env_vars=credential_env_vars,
    )
    manifest = ExperimentManifest(
        run_id=args.run_id,
        agent_code_sha=args.commit,
        evaluator_code_sha=HEAD,
        catalog=lock,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="linux-docker",
        verifier_image_digest=_resolve_digest(task.extensions.get("swebench_image")),
    )
    (output_dir / f"manifest.{args.run_id}.json").write_text(
        manifest.canonical_json() + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "manifest": str(output_dir / f"manifest.{args.run_id}.json"),
                "task_id": task.task_id,
                "run_id": args.run_id,
                "model": model,
                "commit": args.commit,
                "credential_env_vars": credential_env_vars,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _resolve_digest(image: str | None) -> str:
    import re

    if not image:
        raise SystemExit("catalog 任务缺少 swebench_image 扩展字段")
    digest = subprocess.check_output(
        ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        text=True,
    ).strip()
    if not re.fullmatch(r"[A-Za-z0-9./_-]+@sha256:[0-9a-f]{64}", digest):
        raise SystemExit(f"unexpected image digest: {digest!r}")
    return digest.split("@", 1)[1]


if __name__ == "__main__":
    main()
