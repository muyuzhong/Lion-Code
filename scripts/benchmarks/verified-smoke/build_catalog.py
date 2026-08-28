"""生成 flask-5014 冒烟目录卡与冻结锁(受控、可复核)。

从 SWE-bench_Verified 冻结行构造公开任务卡:gold patch SHA-256 作为
provenance hash;public_prompt 为真实 issue 文本(Agent 唯一指令)。
不包含 gold patch、测试 patch 或 verifier 私有信息。

用法:
  python build_catalog.py [--output-dir <dir>]
--output-dir 缺省为脚本自身目录;输出 catalog.json 与 catalog.lock.json。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from datasets import load_dataset

from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.models import Catalog, TaskSpec, TaskSplit

INSTANCE_ID = "pallets__flask-5014"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
    row = next(r for r in ds if r["instance_id"] == INSTANCE_ID)
    gold_hash = hashlib.sha256(row["patch"].encode("utf-8")).hexdigest()
    prompt = (
        "请修复下面这个开源项目的问题。工作区已检出该仓库对应 base commit 的源码,"
        "你可以在工作区内自由阅读、编辑文件并运行测试;遇到需要安装的依赖请自行安装。"
        "把修复后的文件改动留在工作区即可(不要执行 git commit,评测流程会自动"
        "收集你的改动做官方验证,并只按改动内容评判)。\n\n"
        "== 问题描述 ==\n"
        f"{row['problem_statement']}"
    )
    task = TaskSpec(
        task_id="verified-smoke-flask-5014",
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="https://github.com/pallets/flask",
        base_revision=row["base_commit"],
        public_prompt=prompt,
        public_setup=("python -m pip install -e .",),
        public_validation_commands=(
            "python -m pytest -q tests/test_blueprints.py -k empty_name",
        ),
        verifier_identity="swebench-verified/v1",
        gold_evidence_hash=gold_hash,
        difficulty=1,
        involved_files=("src/flask/blueprints.py",),
        extensions={
            "swebench_instance_id": INSTANCE_ID,
            "harbor_task_name": INSTANCE_ID,
            "corpus_version": "smoke",
            "evidence_kind": "swebench-verified",
        },
    )
    catalog = Catalog(
        catalog_id="smoke-verified-v1",
        catalog_version="v1",
        tasks=(task,),
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
                "task_id": task.task_id,
                "instance": INSTANCE_ID,
                "gold_evidence_hash": gold_hash,
                "base_commit": row["base_commit"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()