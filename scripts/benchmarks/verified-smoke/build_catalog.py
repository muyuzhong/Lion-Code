"""从 SWE-bench_Verified 冻结行生成冒烟目录卡与冻结锁(受控、可复核)。

为每个实例构造公开任务卡:gold patch SHA-256 作为 provenance hash;
public_prompt 为真实 issue 文本(Agent 唯一指令)。不包含 gold patch、
测试 patch 或 verifier 私有信息。

用法:
  python build_catalog.py [--output-dir <dir>] [--instances <id1,id2>]
--instances 缺省为 pallets__flask-5014(冒烟单题);可传逗号分隔的多个
SWE-bench 实例 id 生成多任务 catalog。--output-dir 缺省为脚本自身目录,
输出 catalog.json 与 catalog.lock.json。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from datasets import load_dataset

from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.models import Catalog, TaskSpec, TaskSplit

DEFAULT_INSTANCES = ("pallets__flask-5014",)
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _task_id(instance_id: str) -> str:
    """实例 id 到公开任务 id 的稳定映射:下划线换连字符。"""
    task_id = "verified-" + instance_id.replace("__", "-")
    if not ID_PATTERN.fullmatch(task_id):
        raise SystemExit(f"instance id 无法映射为合法 task_id: {instance_id!r}")
    return task_id


def _build_prompt(problem_statement: str) -> str:
    return (
        "请修复下面这个开源项目的问题。工作区已检出该仓库对应 base commit 的源码,"
        "你可以在工作区内自由阅读、编辑文件并运行测试;遇到需要安装的依赖请自行安装。"
        "把修复后的文件改动留在工作区即可(不要执行 git commit,评测流程会自动"
        "收集你的改动做官方验证,并只按改动内容评判)。\n\n"
        "== 问题描述 ==\n"
        f"{problem_statement}"
    )


def _difficulty_int(value: str) -> int:
    """数据集 difficulty 标签到 1-5 分档;未知标签回退为 2。"""
    mapping = {
        "<15 min fix": 1,
        "15 min - 1 hour": 2,
        "1-4 hours": 3,
        ">4 hours": 4,
    }
    return mapping.get(value.strip(), 2)


def _involved_files(patch: str) -> tuple[str, ...]:
    """从 gold patch 解析涉及文件(仅文件名,不含补丁内容)。"""
    files: list[str] = []
    for match in re.finditer(r"^diff --git a/(\S+) b/\S+\s*$", patch, re.MULTILINE):
        name = match.group(1)
        if name not in files:
            files.append(name)
    return tuple(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument(
        "--instances",
        default=",".join(DEFAULT_INSTANCES),
        help="逗号分隔的 SWE-bench_Verified 实例 id",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    instance_ids = tuple(
        item.strip() for item in args.instances.split(",") if item.strip()
    )
    if not instance_ids:
        raise SystemExit("--instances 为空:至少需要一个实例 id")

    ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
    rows = {row["instance_id"]: row for row in ds}
    missing = [iid for iid in instance_ids if iid not in rows]
    if missing:
        raise SystemExit(f"数据集缺少实例: {missing!r}")

    tasks: list[TaskSpec] = []
    for iid in instance_ids:
        row = rows[iid]
        gold_hash = hashlib.sha256(row["patch"].encode("utf-8")).hexdigest()
        tasks.append(
            TaskSpec(
                task_id=_task_id(iid),
                family="bugfix",
                split=TaskSplit.REGRESSION,
                repository=f"https://github.com/{row['repo']}",
                base_revision=row["base_commit"],
                public_prompt=_build_prompt(row["problem_statement"]),
                verifier_identity="swebench-verified/v1",
                gold_evidence_hash=gold_hash,
                difficulty=_difficulty_int(str(row.get("difficulty", ""))),
                involved_files=_involved_files(row["patch"]),
                extensions={
                    "swebench_instance_id": iid,
                    "harbor_task_name": iid,
                    "swebench_image": row["image"],
                    "corpus_version": "smoke",
                    "evidence_kind": "swebench-verified",
                },
            )
        )
    catalog = Catalog(
        catalog_id="smoke-verified-v1",
        catalog_version="v1",
        tasks=tuple(tasks),
    )
    lock = freeze_catalog(catalog)
    (output_dir / "catalog.json").write_text(
        catalog.canonical_json() + "\n", encoding="utf-8"
    )
    (output_dir / "catalog.lock.json").write_text(
        lock.canonical_json() + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "catalog_sha256": lock.catalog_sha256,
                "task_ids": [task.task_id for task in tasks],
                "instances": instance_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
