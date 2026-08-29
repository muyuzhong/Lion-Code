"""实例环境可判定性预检：用官方 gold patch 跑一次官方 Harness。

目的：SWE-bench Verified 镜像在 Python 3.11 环境下可能因 PASS_TO_PASS
环境回归导致连 gold patch 都判不过（如 requests-5414）。预检把这类
"环境不可判定"实例提前识别，批量统计时可剔除分母，避免把环境漂移
误算成 agent 失败。只读本地数据集缓存与官方 Harness，不重跑 agent。

用法：
  HF_HOME=<hf-home> XDG_CACHE_HOME=<xdg-cache> python gold_preflight.py \
      <instance-id> --work-dir <dir> [--harness-python <py>] [--timeout 1800]

stdout 输出一行 JSON：
  {"instance_id": ..., "gold_resolved": bool|None, "status": ...,
   "reason": ..., "tests_summary": {...}}
status: resolved | unresolved | error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from datasets import load_dataset  # noqa: E402


def _gold_patch(instance_id: str) -> str:
    ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
    row = next(r for r in ds if r["instance_id"] == instance_id)
    return row["patch"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance_id")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--harness-python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        patch = _gold_patch(args.instance_id)
    except Exception as error:  # noqa: BLE001 - 预检工具需要兜底
        print(
            json.dumps(
                {
                    "instance_id": args.instance_id,
                    "gold_resolved": None,
                    "status": "error",
                    "reason": f"数据集读取失败: {error}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return

    prediction = {
        "instance_id": args.instance_id,
        "model_name_or_path": "gold-preflight",
        "model_patch": patch,
    }
    predictions = work_dir / "gold-predictions.jsonl"
    predictions.write_text(
        json.dumps(prediction, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    command = [
        str(args.harness_python),
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        "SWE-bench/SWE-bench_Verified",
        "--split",
        "test",
        "--instance_ids",
        args.instance_id,
        "--predictions_path",
        str(predictions),
        "--max_workers",
        "1",
        "--run_id",
        "gold-preflight",
        "--timeout",
        str(max(1, round(args.timeout))),
        "--report_dir",
        str(work_dir / "reports"),
    ]
    try:
        process = subprocess.run(
            command,
            cwd=work_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60, round(args.timeout) + 60),
        )
    except subprocess.TimeoutExpired:
        _emit(args.instance_id, None, "error", "官方 Harness 预检超时")
        return
    report = _find_report(work_dir, args.instance_id)
    if report is None:
        _emit(
            args.instance_id,
            None,
            "error",
            f"官方 Harness 未产出报告(exit={process.returncode}): "
            + (process.stdout[-200:] if process.stdout else "无输出"),
        )
        return
    instance = report.get(args.instance_id)
    if not isinstance(instance, Mapping) or not isinstance(
        instance.get("resolved"), bool
    ):
        _emit(args.instance_id, None, "error", "官方报告缺少 boolean resolved")
        return
    resolved = instance["resolved"]
    if resolved:
        status = "resolved"
        reason = None
    else:
        status = "unresolved"
        reason = "gold patch 亦未通过官方判定，实例环境不可判定（多为镜像环境漂移）"
    _emit(args.instance_id, resolved, status, reason)


def _find_report(work_dir: Path, instance_id: str) -> dict | None:
    """定位官方 per-instance 报告。

    官方 run_evaluation 在 report_dir 写 aggregate 摘要（顶层统计字段、
    无 instance_id 键），per-instance 报告位于
    ``logs/run_evaluation/<run_id>/<model>/<instance>/report.json``，
    其顶层以 instance_id 为键、值含 boolean resolved。
    """

    per_instance = list((work_dir / "logs" / "run_evaluation").rglob("report.json"))
    per_instance.extend((work_dir / "logs" / "run_evaluation").rglob("*.json"))
    for candidate in sorted(set(per_instance)):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and instance_id in payload:
            instance = payload[instance_id]
            if isinstance(instance, Mapping) and isinstance(
                instance.get("resolved"), bool
            ):
                return payload
    return None


def _emit(instance_id: str, resolved, status: str, reason: str | None) -> None:
    print(
        json.dumps(
            {
                "instance_id": instance_id,
                "gold_resolved": resolved,
                "status": status,
                "reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
