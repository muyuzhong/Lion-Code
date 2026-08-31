"""可选的 DeepEval traced pytest 入口；默认不触发网络或 Agent 运行。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchmarks.agent_e2e.analysis_trace import load_analysis_trace
from benchmarks.agent_e2e.deepeval_analysis import (
    DEEPEVAL_METRIC_NAMES,
    analyze_verified_report,
)
from benchmarks.agent_e2e.models import (
    DeepEvalAnalysisStatus,
    VerifiedEvaluationReport,
)


def test_lion_swebench_verified_analysis_trace() -> None:
    """使用已落盘 Verified 结果调用共享分析 API，不再次执行 Agent。"""

    analysis_trace_path = os.environ.get("LION_VERIFIED_ANALYSIS_TRACE")
    report_path = os.environ.get("LION_VERIFIED_REPORT")
    input_digest = os.environ.get("LION_VERIFIED_INPUT_DIGEST")
    judge_model = os.environ.get("LION_DEEPEVAL_JUDGE_MODEL")
    if not all((analysis_trace_path, report_path, input_digest, judge_model)):
        pytest.skip(
            "set LION_VERIFIED_ANALYSIS_TRACE, LION_VERIFIED_REPORT, "
            "LION_VERIFIED_INPUT_DIGEST and LION_DEEPEVAL_JUDGE_MODEL for the online smoke"
        )
    analysis_trace = load_analysis_trace(Path(analysis_trace_path))
    report = VerifiedEvaluationReport.from_json(
        Path(report_path).read_text(encoding="utf-8")
    )
    analyzed = analyze_verified_report(
        report,
        input_digest=input_digest,
        analysis_trace=analysis_trace,
        judge_model=judge_model,
    )
    assert analyzed.deepeval is not None
    assert analyzed.deepeval.status is DeepEvalAnalysisStatus.COMPLETED
    assert (
        tuple(metric.name for metric in analyzed.deepeval.metrics)
        == DEEPEVAL_METRIC_NAMES
    )
    assert analyzed.task_result == report.task_result
