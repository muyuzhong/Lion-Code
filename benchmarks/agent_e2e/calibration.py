"""过程判定校准:验证 ProcessVerifier 在真实语义链路上的召回与精确率。

校准集按夹具目录组织(见 ``tests/benchmarks/fixtures/agent_e2e/calibration/``):

- ``violations/``:已知违规轨迹(typed event dicts + 期望违规),
  验证召回——规则必须命中;
- ``clean/``:正常轨迹,验证不误杀——不得产生 critical_veto;
- ``legacy/``:旧格式 trace 文件(无 evidence),验证降级不崩溃。

violations/clean 夹具从 typed event dicts 起步,**先走 TraceRecorder
投影**(与生产同链路),再交给 ProcessVerifier 判定;这校准的不是
单测 HLP,而是「投影 + 规则」的端到端信任。legacy 夹具直接调用
``verify_file`` 语义(事件存在、证据缺失),验证降级路径。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evidence import ProcessEvidenceProjector
from .models import (
    AgentRunSummary,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)
from .process_verifier import (
    ProcessVerification,
    ProcessVerifier,
    verify_file,
)
from .trace import TraceRecorder


@dataclass(frozen=True, slots=True)
class CalibrationOutcome:
    """单个夹具的执行结果。"""

    fixture_id: str
    kind: str
    passed: bool
    verification: ProcessVerification
    expected_type: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CalibrationSummary:
    """校准集汇总:召回(违规检出)与精确率(正常不误杀)。"""

    outcomes: tuple[CalibrationOutcome, ...]
    legacy_unavailable_ratio: float = 0.0

    @property
    def passed_count(self) -> int:
        return sum(outcome.passed for outcome in self.outcomes)

    def render_markdown(self) -> str:
        lines = [
            "# ProcessVerifier 校准小结",
            "",
            f"- 夹具总数: {len(self.outcomes)}",
            f"- 通过: {self.passed_count}",
            f"- 旧 trace 降级率: {self.legacy_unavailable_ratio:.1%}",
            "",
            "| fixture | kind | 结果 | 期望 | 实际 |",
            "|---|---|---|---|---|",
        ]
        for outcome in self.outcomes:
            lines.append(
                f"| {outcome.fixture_id} | {outcome.kind} | "
                f"{'✅' if outcome.passed else '❌'} | "
                f"{outcome.expected_type or '-'} | "
                f"{outcome.verification.status.value} |"
            )
        for outcome in self.outcomes:
            if not outcome.passed:
                lines.append("")
                lines.append(f"### 失败: {outcome.fixture_id}")
                lines.append(f"```text\n{outcome.detail}\n```")
        return "\n".join(lines) + "\n"


def run_calibration(
    fixtures_root: str | Path,
    *,
    verifier: ProcessVerifier | None = None,
) -> CalibrationSummary:
    """运行 fixtures 目录下的全部校准夹具,返回可复核小结。"""

    root = Path(fixtures_root)
    outcomes: list[CalibrationOutcome] = []
    for kind in ("violations", "clean", "legacy"):
        kind_root = root / kind
        if not kind_root.is_dir():
            continue
        for fixture_path in sorted(kind_root.glob("*.json")):
            outcomes.append(_run_fixture(fixture_path, kind, verifier))
    legacy_outcomes = [outcome for outcome in outcomes if outcome.kind == "legacy"]
    legacy_count = len(legacy_outcomes)
    legacy_unavailable = sum(
        outcome.verification.status.value == "evidence_unavailable"
        for outcome in legacy_outcomes
    )
    ratio = legacy_unavailable / legacy_count if legacy_count else 0.0
    return CalibrationSummary(
        outcomes=tuple(outcomes),
        legacy_unavailable_ratio=ratio,
    )


def _run_fixture(
    fixture_path: Path,
    kind: str,
    verifier: ProcessVerifier | None,
) -> CalibrationOutcome:
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Fixture must be an object: {fixture_path}")
    fixture_id = str(raw.get("fixture_id", fixture_path.stem))
    task = _task_from_fixture(raw.get("task") or {})
    task_result = _task_result_from_fixture(raw.get("task_result") or {})
    active = verifier or ProcessVerifier()
    if kind == "legacy":
        verification = _verify_legacy_fixture(fixture_path, task, task_result, active)
    else:
        verification = _verify_projected(
            events=tuple(raw.get("events", ())),
            task=task,
            task_result=task_result,
            verifier=active,
        )
    if kind == "violations":
        expected = raw.get("expected") or {}
        expected_type = str((expected.get("violation_types") or [""])[0])
        expected_severity = str(expected.get("severity", ""))
        actual_types = {v.violation_type.value for v in verification.violations}
        passed = expected_type in actual_types
        detail = (
            f"期望 {expected_type}({expected_severity});实际 "
            f"{verification.status.value} / types={sorted(actual_types)}"
        )
        return CalibrationOutcome(
            fixture_id=fixture_id,
            kind=kind,
            passed=passed,
            verification=verification,
            expected_type=expected_type,
            detail=detail,
        )
    if kind == "clean":
        actual_types = {v.violation_type.value for v in verification.violations}
        passed = verification.status.value == "valid"
        detail = f"期望 valid;实际 {verification.status.value} / types={sorted(actual_types)}"
        return CalibrationOutcome(
            fixture_id=fixture_id,
            kind=kind,
            passed=passed,
            verification=verification,
            detail=detail,
        )
    passed = verification.status.value == "evidence_unavailable"
    detail = f"期望 evidence_unavailable;实际 {verification.status.value}"
    return CalibrationOutcome(
        fixture_id=fixture_id,
        kind=kind,
        passed=passed,
        verification=verification,
        detail=detail,
    )


def _verify_projected(
    *,
    events: tuple[dict[str, Any], ...],
    task: TaskSpec,
    task_result: TaskResult,
    verifier: ProcessVerifier,
) -> ProcessVerification:
    recorder = TraceRecorder(
        projector=ProcessEvidenceProjector(
            validation_commands=task.public_validation_commands,
        )
    )
    for event in events:
        recorder.record(event)
    return verifier.verify(
        task=task,
        task_result=task_result,
        trace_events=recorder.events,
        evidence=recorder.evidence,
    )


def _verify_legacy_fixture(
    fixture_path: Path,
    task: TaskSpec,
    task_result: TaskResult,
    verifier: ProcessVerifier,
) -> ProcessVerification:
    # 旧格式夹具的顶层就是 harbor-trace.json 内容(只有 events,
    # 无 evidence),与 verify_file 的读取语义完全一致。
    return verify_file(
        fixture_path,
        task=task,
        task_result=task_result,
        verifier=verifier,
    )


def _task_from_fixture(payload: dict[str, Any]) -> TaskSpec:
    return TaskSpec(
        task_id=str(payload.get("task_id", "calibration-task")),
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="校准夹具任务。",
        public_setup=(),
        public_validation_commands=tuple(
            payload.get("validation_commands", ("python -m pytest -q",))
        ),
        verifier_identity="hidden-v1",
        gold_evidence_hash="a" * 64,
        difficulty=2,
        involved_files=(),
    )


def _task_result_from_fixture(payload: dict[str, Any]) -> TaskResult:
    passed = payload.get("verdict", "passed") == "passed"
    outcome = VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
    verdict = TaskVerdict.PASSED if passed else TaskVerdict.FAILED
    return TaskResult(
        task_id="calibration-task",
        attempt=int(payload.get("attempt", 1)),
        verdict=verdict,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256="b" * 64,
        agent_run=AgentRunSummary(
            final_text_digest="c" * 64,
            stop_reason=str(payload.get("stop_reason", "completed")),
            turns=3,
            wall_time_seconds=1,
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=0,
            cost_usd=0.1,
        ),
        verifier=VerifierResult(
            outcome=outcome,
            command_summary="hidden verifier",
            exit_code=0 if passed else 1,
            output_digest="d" * 64,
        ),
    )


__all__ = [
    "CalibrationOutcome",
    "CalibrationSummary",
    "run_calibration",
]
