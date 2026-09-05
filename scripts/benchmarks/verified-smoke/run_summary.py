"""SWE-bench Verified 批量 run-level 汇总报告(首次正式测评交付物)。

扫描 run-root 下所有 ``run-*/verified-report.json``,聚合官方判定并
对失败题做可解释性归因(ProcessVerifier 过程违规 + DeepEval 指标信号),
输出 ``run-summary.json`` 与 ``run-summary.md``。

归因只回答三类问题:过了多少、失败主要是什么类型、评测体系还解释不了
多少。DeepEval 只统计分布与典型低分,不合成"DeepEval 总分"。

用法:
  python run_summary.py --run-root <batch-work-dir> --catalog <catalog.json>
  # --run-root 为 run_batch.sh 的 WORK_DIR(含 run-*/verified-report.json)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from benchmarks.agent_e2e.catalog import load_catalog
from benchmarks.agent_e2e.models import TaskVerdict
from benchmarks.agent_e2e.process_verifier import (
    ProcessViolationType,
    verify_file,
)

DEEPEVAL_THRESHOLD = 0.5  # 与评测链运行侧策略常量一致

# 归因类别(按优先级:过程违规信号最确定,DeepEval 其次,最后是无法归因)
ATTRIBUTION_LABELS = {
    ProcessViolationType.TOOL_ERROR_NOT_RECOVERED.value: "工具错误后恢复失败",
    ProcessViolationType.PREMATURE_TERMINATION.value: "提前结束",
}


def _load_report(run_dir: Path) -> dict | None:
    report_path = run_dir / "verified-report.json"
    if not report_path.is_file():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _instance_id(report: dict, catalog_tasks: dict[str, dict]) -> str | None:
    task_id = (report.get("task_result") or {}).get("task_id")
    if not task_id:
        return None
    task = catalog_tasks.get(task_id)
    if task is not None:
        return task.extensions.get("swebench_instance_id")
    return task_id


def _deepeval_metrics(report: dict) -> list[dict]:
    analysis = report.get("deepeval")
    if not isinstance(analysis, dict):
        return []
    metrics = analysis.get("metrics")
    if not isinstance(metrics, list):
        return []
    rows = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        rows.append(
            {
                "name": metric.get("name"),
                "status": metric.get("status"),
                "score": metric.get("score"),
                "score_min": metric.get("score_min"),
                "score_max": metric.get("score_max"),
                "threshold_met": metric.get("threshold_met"),
                "reason": metric.get("reason"),
            }
        )
    return rows


def _process_attribution(run_dir: Path, report: dict, catalog_tasks: dict) -> list[str]:
    """ProcessVerifier 归因:读取受控轨迹,返回违规类型标签列表。"""
    task_id = (report.get("task_result") or {}).get("task_id")
    if not task_id:
        return []
    task_spec = catalog_tasks.get(task_id)
    if task_spec is None:
        return []
    trace_path = run_dir / "artifacts" / "harbor-trace.json"
    if not trace_path.is_file():
        return []
    try:
        task_result_model = _task_result_model(report)
        verification = verify_file(
            trace_path,
            task=task_spec,
            task_result=task_result_model,
        )
    except Exception:  # noqa: BLE001 - 归因失败不阻断汇总
        return []
    return [
        violation.violation_type.value
        for violation in verification.violations
        if violation.violation_type
        in (
            ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
            ProcessViolationType.PREMATURE_TERMINATION,
        )
    ]


def _task_result_model(report: dict):
    """按运行期 schema 重建 TaskResult 模型(字段缺省时容忍)。"""
    from benchmarks.agent_e2e.models import TaskResult

    task_result = report.get("task_result") or {}
    try:
        return TaskResult.model_validate(task_result)
    except Exception:  # noqa: BLE001
        return None


def _classify(report: dict) -> str:
    """结果归类:passed | failed | blocked。"""
    task_result = report.get("task_result") or {}
    verdict = task_result.get("verdict")
    if verdict == TaskVerdict.PASSED.value:
        return "passed"
    if verdict == TaskVerdict.FAILED.value:
        return "failed"
    return "blocked"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    if not run_root.is_dir():
        print(f"错误:run-root 不存在 {run_root}", file=sys.stderr)
        return 2
    catalog = load_catalog(args.catalog)
    catalog_tasks = {task.task_id: task for task in catalog.tasks}

    reports: list[dict] = []
    for run_dir in sorted(run_root.glob("run-*")):
        report = _load_report(run_dir)
        if report is not None:
            reports.append({"run_dir": run_dir, "report": report})

    rows: list[dict] = []
    for item in reports:
        run_dir, report = item["run_dir"], item["report"]
        task_result = report.get("task_result") or {}
        harness = report.get("harness") or {}
        row = {
            "instance_id": _instance_id(report, catalog_tasks),
            "run_dir": run_dir.name,
            "class": _classify(report),
            "verdict": task_result.get("verdict"),
            "validity": task_result.get("validity"),
            "invalid_reason": task_result.get("invalid_reason"),
            "official_resolved": harness.get("resolved"),
            "harbor_reward": (report.get("harbor") or {}).get("reward"),
            "cost_usd": task_result.get("cost_usd"),
            "stop_reason": (task_result.get("agent_run") or {}).get("stop_reason"),
            "attributions": _process_attribution(run_dir, report, catalog_tasks),
            "deepeval": _deepeval_metrics(report),
        }
        rows.append(row)

    counts = Counter(row["class"] for row in rows)
    failed_rows = [row for row in rows if row["class"] == "failed"]

    # 失败归因聚合:优先过程违规,其次 DeepEval 低分信号,最后无法归因
    attribution_counts: Counter[str] = Counter()
    deep_eval_low: Counter[str] = Counter()
    unattributed: list[str] = []
    for row in failed_rows:
        labels = [ATTRIBUTION_LABELS[a] for a in row["attributions"] if a in ATTRIBUTION_LABELS]
        if labels:
            attribution_counts.update(set(labels))
            row["attribution"] = "、".join(sorted(set(labels)))
            continue
        low_metrics = [
            m["name"]
            for m in row["deepeval"]
            if isinstance(m.get("score"), (int, float))
            and m["score"] < DEEPEVAL_THRESHOLD
        ]
        if low_metrics:
            deep_eval_low.update(set(low_metrics))
            row["attribution"] = f"DeepEval 低分信号({', '.join(sorted(set(low_metrics)))})"
            continue
        unattributed.append(row["instance_id"] or row["run_dir"])
        row["attribution"] = "当前无法可靠归因"

    # DeepEval 指标分布(仅统计,不合成总分)
    metric_scores: dict[str, list[float]] = {}
    metric_low_cases: dict[str, list[str]] = {}
    for row in rows:
        for metric in row["deepeval"]:
            name = metric["name"]
            if not name:
                continue
            metric_scores.setdefault(name, [])
            if isinstance(metric.get("score"), (int, float)):
                metric_scores[name].append(metric["score"])
                if metric["score"] < DEEPEVAL_THRESHOLD:
                    metric_low_cases.setdefault(name, []).append(
                        row["instance_id"] or row["run_dir"]
                    )

    summary = {
        "schema_version": "verified-run-summary/v1",
        "run_root": str(run_root),
        "total": len(rows),
        "counts": dict(counts),
        "failure_attribution": {
            "process_violations": dict(attribution_counts),
            "deepeval_low_signals": dict(deep_eval_low),
            "unattributed": unattributed,
        },
        "deepeval_distribution": {
            name: {
                "n": len(scores),
                "mean": round(sum(scores) / len(scores), 3) if scores else None,
                "low_score_cases": metric_low_cases.get(name, []),
            }
            for name, scores in metric_scores.items()
        },
        "rows": rows,
    }
    (run_root / "run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    lines = [
        "# SWE-bench Verified 批量汇总报告",
        "",
        f"- 总题数:{len(rows)};官方通过 {counts['passed']} 个,"
        f"失败 {counts['failed']} 个,环境/基础设施不可判定 {counts['blocked']} 个。",
    ]
    if failed_rows:
        lines.append("")
        lines.append("## 失败归因")
        lines.append("")
        lines.append("| 实例 | 归因 | 过程违规 | DeepEval 低分 | 停止原因 |")
        lines.append("|---|---|---|---|---|")
        for row in failed_rows:
            proc = "、".join(
                ATTRIBUTION_LABELS.get(a, a) for a in row["attributions"]
            ) or "—"
            deep = "、".join(
                sorted(
                    {
                        m["name"]
                        for m in row["deepeval"]
                        if isinstance(m.get("score"), (int, float))
                        and m["score"] < DEEPEVAL_THRESHOLD
                    }
                )
            ) or "—"
            lines.append(
                f"| {row['instance_id'] or row['run_dir']} | {row['attribution']} "
                f"| {proc} | {deep} | {row['stop_reason'] or '—'} |"
            )
    if metric_scores:
        lines.append("")
        lines.append("## DeepEval 指标分布(不合成总分)")
        lines.append("")
        lines.append("| 指标 | 样本数 | 均值 | 低分(<0.5)典型 case |")
        lines.append("|---|---|---|---|")
        for name, info in summary["deepeval_distribution"].items():
            cases = "、".join(info["low_score_cases"][:5]) or "—"
            lines.append(
                f"| {name} | {info['n']} | {info['mean']} | {cases} |"
            )
    (run_root / "run-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(rows), "counts": dict(counts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
