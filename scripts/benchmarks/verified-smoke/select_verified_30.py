"""SWE-bench Verified 首次正式测评的分层抽样(可复现、仓库分散)。

第一次正式测评固定抽 30 题:10 easy / 15 medium / 5 hard(配额写死,
不随数据集版本漂移)。难度映射使用官方时间桶标注:

- easy   = "<15 min fix"           (Verified 共 194 个)
- medium = "15 min - 1 hour"       (共 261 个)
- hard   = "1-4 hours" + ">4 hours" (共 45 个,与官方 45 hard 一致)

排除已跑过(看过结果)的实例,避免污染"新实例"口径:
pallets__flask-5014 / psf__requests-5414 / pytest-dev__pytest-6202。

层内抽样用仓库轮转:每轮按仓库实例数降序,每个仓库随机取 1 个,
配额满即停;保证 30 题覆盖尽量多仓库、且不出现单仓库垄断。

用法:
  python select_verified_30.py --dataset <verified_dataset.json> --output-dir <dir>
输出 selection.json(机器可读)与 selection.md(人读清单)。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# 第一次正式测评的固定配额与排除清单(历史已跑过、看过结果的实例)
QUOTAS: dict[str, int] = {"easy": 10, "medium": 15, "hard": 5}
EXCLUDED: tuple[str, ...] = (
    "pallets__flask-5014",
    "psf__requests-5414",
    "pytest-dev__pytest-6202",
    "django__django-11555",  # 单题端到端冒烟已跑过,结果已见
)
SEED = 20260904  # 固定随机种子,保证抽样可复现

DIFFICULTY_BUCKETS: dict[str, tuple[str, ...]] = {
    "easy": ("<15 min fix",),
    "medium": ("15 min - 1 hour",),
    "hard": ("1-4 hours", ">4 hours"),
}


def _difficulty_key(instance_id: str, row: dict) -> str:
    label = str(row.get("difficulty", "")).strip()
    for key, buckets in DIFFICULTY_BUCKETS.items():
        if label in buckets:
            return key
    raise SystemExit(f"实例 {instance_id} 的 difficulty 无法归类: {label!r}")


def _layer_select(
    rng: random.Random,
    layer_instances: list[tuple[str, dict]],
    quota: int,
) -> list[tuple[str, dict]]:
    """层内仓库轮转抽样:每轮按仓库实例数降序,每仓库随机取 1,配额满即停。"""
    by_repo: dict[str, list[tuple[str, dict]]] = {}
    for iid, row in layer_instances:
        by_repo.setdefault(str(row["repo"]), []).append((iid, row))
    selected: list[tuple[str, dict]] = []
    while len(selected) < quota and by_repo:
        for repo in sorted(by_repo, key=lambda r: (-len(by_repo[r]), r)):
            if len(selected) >= quota:
                break
            pool = by_repo[repo]
            pick = rng.choice(pool)
            pool.remove(pick)
            selected.append(pick)
            if not pool:
                del by_repo[repo]
    if len(selected) < quota:
        raise SystemExit(
            f"层内可抽实例不足:需求 {quota},实际 {len(selected)}"
        )
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="本地 verified 数据集 JSON")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    with Path(args.dataset).open(encoding="utf-8") as handle:
        rows = json.load(handle)

    layers: dict[str, list[tuple[str, dict]]] = {"easy": [], "medium": [], "hard": []}
    for iid, row in rows.items():
        if iid in EXCLUDED:
            continue
        layers[_difficulty_key(iid, row)].append((iid, row))
    for key, items in layers.items():
        print(f"层 {key}: 可抽实例 {len(items)} 个(配额 {QUOTAS[key]})")

    rng = random.Random(SEED)
    selection: dict[str, dict] = {}
    for key, quota in QUOTAS.items():
        for iid, row in _layer_select(rng, layers[key], quota):
            selection[iid] = {
                "instance_id": iid,
                "repo": row["repo"],
                "base_commit": row["base_commit"],
                "difficulty": str(row["difficulty"]),
                "difficulty_key": key,
            }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "verified-selection/v1",
        "seed": SEED,
        "quota": QUOTAS,
        "excluded": list(EXCLUDED),
        "difficulty_buckets": DIFFICULTY_BUCKETS,
        "instances": selection,
    }
    (output_dir / "selection.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    lines = [
        "# SWE-bench Verified 首次正式测评抽样(30 题)",
        "",
        f"- 抽样 seed:{SEED}",
        f"- 配额:10 easy / 15 medium / 5 hard",
        f"- 排除已跑过实例:{', '.join(EXCLUDED)}",
        "",
        "| 实例 id | 仓库 | 难度桶 |",
        "|---|---|---|",
    ]
    for iid in sorted(selection, key=lambda i: selection[i]["difficulty_key"]):
        item = selection[iid]
        lines.append(
            f"| {iid} | {item['repo']} | {item['difficulty']}({item['difficulty_key']}) |"
        )
    (output_dir / "selection.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"抽样完成:{len(selection)} 题,输出到 {output_dir}/selection.{{json,md}}")
    for iid in sorted(selection, key=lambda i: selection[i]["difficulty_key"]):
        item = selection[iid]
        print(f"  [{item['difficulty_key']}] {iid} ({item['repo']})")


if __name__ == "__main__":
    main()
