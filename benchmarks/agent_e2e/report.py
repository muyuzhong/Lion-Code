"""严格 JSON 与中文 Markdown 报告；离线运行不得伪造正式成绩。"""

from __future__ import annotations

from pathlib import Path

from .models import (
    EvaluationReport,
    ExperimentManifest,
    OfficialScore,
    ReportStatus,
    TaskResult,
    TaskVerdict,
)


def build_report(
    *,
    manifest: ExperimentManifest,
    results: tuple[TaskResult, ...] | list[TaskResult],
) -> EvaluationReport:
    """根据结果生成报告；没有隔离正式结果时明确省略 official_score。"""

    frozen_results = tuple(results)
    official_results = tuple(result for result in frozen_results if result.official)
    if official_results:
        passed_count = sum(
            result.verdict is TaskVerdict.PASSED for result in official_results
        )
        failed_count = sum(
            result.verdict is TaskVerdict.FAILED for result in official_results
        )
        denominator = len(official_results)
        score = OfficialScore(
            passed_count=passed_count,
            failed_count=failed_count,
            valid_denominator=denominator,
            success_rate=passed_count / denominator,
        )
        return EvaluationReport(
            manifest=manifest,
            results=frozen_results,
            status=ReportStatus.OFFICIAL,
            official_score=score,
        )
    if frozen_results and all(
        result.verdict is TaskVerdict.BLOCKED for result in frozen_results
    ):
        status = ReportStatus.BLOCKED
    else:
        status = ReportStatus.OFFLINE
    return EvaluationReport(
        manifest=manifest,
        results=frozen_results,
        status=status,
    )


def render_chinese_markdown(report: EvaluationReport) -> str:
    """渲染不含凭证、session 或未隔离正式分数的中文报告。"""

    lines = [
        "# 编码 Agent 评测报告",
        "",
        f"- 运行 ID：`{report.manifest.run_id}`",
        f"- 配置指纹：`{report.manifest.profile_fingerprint}`",
        f"- Catalog SHA-256：`{report.manifest.catalog.catalog_sha256}`",
        f"- 任务数：{len(report.results)}",
        f"- 报告状态：{_status_label(report.status)}",
    ]
    if report.official_score is None:
        lines.extend(
            [
                "- 正式成绩：未生成（当前结果未满足真实容器隔离与后置验收条件）",
                "",
                "## 离线/阻塞证据",
            ]
        )
    else:
        score = report.official_score
        lines.extend(
            [
                f"- 正式成功率：{score.success_rate:.1%} "
                f"（{score.passed_count}/{score.valid_denominator}）",
                "",
                "## 单题结果",
            ]
        )
    if not report.results:
        lines.append("- 暂无单题结果。")
    for result in report.results:
        reason = f"；原因：{result.invalid_reason}" if result.invalid_reason else ""
        lines.append(
            f"- `{result.task_id}` / 第 {result.attempt} 次："
            f"{result.verdict.value}（{result.validity.value}）{reason}"
        )
    return "\n".join(lines) + "\n"


def write_report(
    report: EvaluationReport,
    *,
    output_dir: str | Path,
    stem: str = "report",
) -> tuple[Path, Path]:
    """将 JSON 和中文 Markdown 写到调用方控制的结果目录。"""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    json_path.write_text(report.canonical_json() + "\n", encoding="utf-8")
    markdown_path.write_text(render_chinese_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _status_label(status: ReportStatus) -> str:
    labels = {
        ReportStatus.BLOCKED: "已阻塞",
        ReportStatus.OFFLINE: "仅离线验证",
        ReportStatus.OFFICIAL: "正式隔离结果",
    }
    return labels[status]
