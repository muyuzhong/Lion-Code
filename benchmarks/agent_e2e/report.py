"""严格 JSON 与中文 Markdown 报告；离线运行不得伪造正式成绩。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import (
    AdapterStatus,
    EvaluationReport,
    ExperimentManifest,
    OfficialScore,
    OpikExportResult,
    ReportStatus,
    TaskResult,
    TaskVerdict,
    VerifiedEvaluationReport,
    VerifierOutcome,
)
from .trace import redact_text


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


def render_verified_markdown(report: VerifiedEvaluationReport) -> str:
    """渲染 Verified 四段结果，只展示受控摘要和非敏感引用。"""

    task_result = report.task_result
    lines = [
        "# SWE-bench Verified 单题评测报告",
        "",
        f"- 运行 ID：`{_safe_display(report.manifest.run_id, 128)}`",
        f"- 任务 ID：`{_safe_display(task_result.task_id, 160)}`",
        f"- Commit：`{_safe_display(report.manifest.agent_code_sha, 128)}`",
        f"- 配置指纹：`{_safe_display(report.manifest.profile_fingerprint, 64)}`",
        f"- 报告状态：{_status_label(report.status)}",
        f"- 执行状态：{_trial_status(report)}",
        f"- 任务得分：{task_result.verdict.value}；有效性：{task_result.validity.value}；"
        f"正式结果：{'是' if task_result.official else '否'}",
        f"- Agent 成本：{task_result.cost_usd:.6f} USD；耗时："
        f"{_duration(task_result.finished_at, task_result.started_at):.3f} 秒",
        "",
        "## 产物与 provenance",
    ]
    provenance = report.provenance
    if provenance is None:
        lines.append("- 未生成 commit 产物 provenance。")
    else:
        lines.extend(
            [
                f"- Git tree：`{_safe_display(provenance.git_tree_sha, 128)}`",
                f"- Wheel SHA-256：`{_safe_display(provenance.wheel_sha256, 64)}`",
                f"- Wheel：`{_safe_display(provenance.wheel_filename, 240)}`",
                f"- 镜像：`{_safe_display(provenance.image_digest, 320)}`",
                f"- 依赖版本：Harbor {_safe_display(provenance.harbor_version, 128)}；"
                f"SWE-bench {_safe_display(provenance.swebench_version, 128)}；"
                f"DeepEval {_safe_display(provenance.deepeval_version, 128)}；"
                f"Opik {_safe_display(provenance.opik_version, 128)}",
            ]
        )

    lines.extend(["", "## 四段结果"])
    _append_process_metrics(lines, report)
    _append_harbor(lines, report)
    _append_harness(lines, report)
    _append_deepeval(lines, report)
    _append_opik(lines, report.opik)
    return "\n".join(lines) + "\n"


def _append_process_metrics(lines: list[str], report: VerifiedEvaluationReport) -> None:
    """渲染规则化的过程指标(确定性行为画像,不评判对错)。"""
    metrics = report.extensions.get("process_metrics")
    if not isinstance(metrics, dict) or "tool_calls" not in metrics:
        return
    counts = metrics.get("tool_counts")
    count_text = (
        ", ".join(f"{name}×{n}" for name, n in sorted(counts.items()))
        if isinstance(counts, dict)
        else "n/a"
    )
    lines.append(
        f"- 行为画像：工具调用 {metrics.get('tool_calls', 'n/a')} 次"
        f"（{count_text}）；首次编辑在第 "
        f"{metrics.get('first_edit_tool_index', 'n/a')} 次工具调用后；"
        f"编辑前 shell 探测 {metrics.get('shell_calls_before_first_edit', 'n/a')} 次；"
        f"同工具最大连续 {metrics.get('max_consecutive_same_tool', 'n/a')} 次；"
        f"轨迹事件 {metrics.get('event_count', 'n/a')} 个。"
    )


def _append_harbor(lines: list[str], report: VerifiedEvaluationReport) -> None:
    harbor = report.harbor
    if harbor is None:
        lines.append("- Harbor：未运行。")
        return
    lines.extend(
        [
            f"- Harbor：状态 `{harbor.status.value}`；reward："
            f"{_optional_number(harbor.reward)}；trial："
            f"`{harbor.execution_status.value}`；verifier："
            f"{_safe_display(harbor.verifier_outcome, 64)}；job："
            f"`{_safe_display(harbor.job_id, 240)}`；patch digest："
            f"`{_safe_display(harbor.patch_sha256, 64)}`；耗时："
            f"{_optional_number(harbor.wall_time_seconds)} 秒",
            f"  - 失败来源：{_safe_display(harbor.failure_source, 64)}；"
            f"原因：{_safe_display(harbor.reason, 320)}",
            f"  - 受控引用：{_safe_refs(harbor.artifact_references)}",
        ]
    )


def _append_harness(lines: list[str], report: VerifiedEvaluationReport) -> None:
    harness = report.harness
    if harness is None:
        lines.append("- 官方 Harness：未运行。")
        return
    lines.extend(
        [
            f"- 官方 Harness：状态 `{harness.status.value}`；resolved："
            f"{_optional_bool(harness.resolved)}；patch digest："
            f"`{_safe_display(harness.patch_sha256, 64)}`；报告 digest："
            f"`{_safe_display(harness.output_digest, 64)}`；评估器："
            f"`{_safe_display(harness.evaluator_revision, 128)}`",
            f"  - 镜像：`{_safe_display(harness.image_digest, 320)}`；"
            f"失败来源：{_safe_display(harness.failure_source, 64)}；"
            f"原因：{_safe_display(harness.reason, 320)}",
        ]
    )
    divergence = _harbor_harness_divergence(report)
    if divergence is not None:
        lines.append(f"  - 分歧标注：{divergence}")
    tests = harness.extensions.get("official_tests")
    if isinstance(tests, dict) and tests.get("status") == "reported":
        ftp = tests.get("fail_to_pass") or {}
        ptp = tests.get("pass_to_pass") or {}
        lines.append(
            f"  - 官方测试明细：FAIL_TO_PASS {ftp.get('passed', 0)}/{ftp.get('total', 0)} 通过；"
            f"PASS_TO_PASS {ptp.get('failed', 0)} 项失败"
        )
        if tests.get("env_regression_suspect"):
            lines.append(
                "  - ⚠️ 环境回归疑似：FAIL_TO_PASS 全部通过但官方 resolved=False，"
                "多为镜像环境漂移（旧项目在新 Python 下 PASS_TO_PASS 失败），"
                "不应判为 agent 修复失败"
            )


def _harbor_harness_divergence(report: VerifiedEvaluationReport) -> str | None:
    """例行 verifier 与官方 Harness 结论冲突时的失败归属文字（仅展示层）。

    reward 只进文字不进 JSON 判定；JSON 保留两段原始字段可推导。
    """

    harbor = report.harbor
    harness = report.harness
    if harbor is None or harness is None:
        return None
    if harbor.status is not AdapterStatus.COMPLETED:
        return None
    if harness.status is not AdapterStatus.COMPLETED:
        return None
    if harbor.verifier_outcome is VerifierOutcome.FAILED and harness.resolved is True:
        return (
            f"Harbor 例行 verifier 判失败(reward {_optional_number(harbor.reward)})"
            "而官方 Harness resolved=true：判定以官方 Harness 为准，Harbor 侧"
            "仅过程证据，reward 不参与判定"
        )
    if harbor.verifier_outcome is VerifierOutcome.PASSED and harness.resolved is False:
        return (
            "Harbor 例行 verifier 判通过而官方 Harness 未通过：判定以官方 Harness 为准"
        )
    return None


def _append_deepeval(lines: list[str], report: VerifiedEvaluationReport) -> None:
    analysis = report.deepeval
    if analysis is None:
        lines.append("- DeepEval：未运行。")
        return
    lines.append(
        f"- DeepEval：状态 `{analysis.status.value}`；Agent 模型："
        f"`{_safe_display(analysis.agent_model, 256)}`；Judge 模型："
        f"`{_safe_display(analysis.judge_model, 256)}`；Judge 指纹："
        f"`{_safe_display(analysis.judge_fingerprint, 64)}`；输入 digest："
        f"`{_safe_display(analysis.input_digest, 64)}`；轨迹 digest："
        f"`{_safe_display(analysis.trajectory_digest, 64)}`"
    )
    for metric in analysis.metrics:
        threshold = (
            f"；阈值 {metric.threshold:.4f}；"
            f"{'达阈值' if metric.threshold_met else '未达阈值'}"
            if metric.threshold is not None
            else ""
        )
        sampling = ""
        if metric.samples > 1:
            sampling = f"；采样 {metric.samples} 次"
            if metric.score_min is not None and metric.score_max is not None:
                sampling += f"；范围 {metric.score_min:.4f}–{metric.score_max:.4f}"
        lines.append(
            f"  - `{_safe_display(metric.name, 160)}`："
            f"{_optional_number(metric.score)}{threshold}{sampling}；"
            f"状态 `{metric.status.value}`；"
            f"原因：{_safe_display(metric.reason, 320)}"
        )
    lines.append(f"  - 门禁结论：{_gate_conclusion(report)}")
    if analysis.reason:
        lines.append(
            f"  - 分析失败来源：{_safe_display(analysis.failure_source, 64)}；"
            f"原因：{_safe_display(analysis.reason, 320)}"
        )


def _gate_conclusion(report: VerifiedEvaluationReport) -> str:
    """确定性判定 + judge 评分门禁的合并展示；分数仅为观测。"""

    verdict = report.task_result.verdict
    deterministic = (
        f"确定性判定 = {verdict.value}(官方 Harness)"
        if report.task_result.official
        else f"确定性判定 = {verdict.value}(无官方结果)"
    )
    gate = report.deepeval.score_gate if report.deepeval is not None else None
    if gate is None:
        return f"{deterministic}；judge 评分门禁：无已评分指标"
    label = "通过" if gate.passed else "未达"
    return (
        f"{deterministic}；judge 评分门禁：{label}"
        f"({gate.passed_metrics}/{gate.evaluated_metrics} 达阈值；"
        "观测，不参与判定)"
    )


def _append_opik(lines: list[str], export: OpikExportResult | None) -> None:
    if export is None:
        lines.append("- Opik Cloud：未发布。")
        return
    lines.append(
        f"- Opik Cloud：状态 `{export.status.value}`；trace ID："
        f"`{_safe_display(export.trace_id, 160)}`；payload digest："
        f"`{_safe_display(export.payload_digest, 64)}`；workspace/project："
        f"`{_safe_display(export.workspace, 160)}` / "
        f"`{_safe_display(export.project, 160)}`；尝试次数：{export.attempts}"
    )
    if export.reason:
        lines.append(
            f"  - 失败来源：{_safe_display(export.failure_source, 64)}；"
            f"原因：{_safe_display(export.reason, 320)}"
        )


def _trial_status(report: VerifiedEvaluationReport) -> str:
    if report.trial is None:
        return "未建立 trial"
    return report.trial.status.value


def _duration(finished: datetime, started: datetime) -> float:
    delta = finished - started
    return max(0.0, delta.total_seconds())


def _optional_bool(value: bool | None) -> str:
    return "未提供" if value is None else ("是" if value else "否")


def _optional_number(value: float | None) -> str:
    return "未提供" if value is None else f"{value:.6f}"


def _safe_refs(values: tuple[str, ...]) -> str:
    if not values:
        return "无"
    return ", ".join(f"`{_safe_display(value, 240)}`" for value in values)


def _safe_display(value: object, max_length: int) -> str:
    if value is None:
        return "未提供"
    value = getattr(value, "value", value)
    text, _ = redact_text(str(value), max_length=max_length)
    return text.replace("\r", " ").replace("\n", " ")


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
