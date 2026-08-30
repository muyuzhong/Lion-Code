"""首次错误定位:在成对 ProcessEvidence 上找第一次有因果意义的偏离。

Gate V2 只回答「这个 Harness 改动整体变差没有」;本模块回答「从哪一步
开始错」。算法三步:

1. 调用级对齐:不按 sequence 硬对齐,把 ProcessEvidence 聚成调用序列
   (按 tool_call_id 聚合,指纹取首个带参阶段),对齐键 =
   (tool_name, fingerprint),共同前缀即第一次 divergence;
2. 判断 divergence 是否真是错误:复用 ProcessVerifier 在 candidate
   证据上跑,取 violations——不是每个不同都是错误,只有后续出现失败
   证据才提升为 first error;
3. 按固定优先级定位 first error:critical veto > 未恢复错误 >
   validation 缺失 > compaction 后重复 > premature termination >
   普通行为 divergence(仅当 baseline PASS → candidate FAIL 时产出
   低置信候选;PASS→PASS 的不同实现路径不是 first error,返回 None)。

输出一个短因果片段(baseline_events / candidate_events,红acted 摘要
行),供后续 regression_probe 做前缀最小化。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from pydantic import Field

from .evidence import ProcessEvidence, ToolPhase
from .models import TaskResult, TaskSpec, TaskVerdict, VersionedModel
from .process_verifier import (
    ProcessVerification,
    ProcessVerifier,
    ProcessViolation,
    ProcessViolationType,
)


class FirstErrorKind(str, Enum):
    """首次错误的类型;TOOL_SELECTION/TOOL_ARGUMENT 属于低置信行为分歧。"""

    TOOL_SELECTION = "tool_selection"
    TOOL_ARGUMENT = "tool_argument"
    ERROR_RECOVERY = "error_recovery"
    VALIDATION = "validation"
    CONTEXT = "context"
    TERMINATION = "termination"
    PROCESS_VIOLATION = "process_violation"
    UNKNOWN = "unknown"


class FirstErrorAttribution(VersionedModel):
    """一次 first-error 定位:类型 + 置信度 + 两侧序列位置 + 因果片段。

    ``evidence_available`` 为 False 表示任一侧过程证据不可用(空
    evidence,如旧格式轨迹),此时其它字段不携带归因语义,只说明
    「无法归因」——不要把「没测」误报成「没有 first error」。
    """

    task_id: str = Field(min_length=1, max_length=128)
    attempt: int | None = Field(default=None, ge=1)
    kind: FirstErrorKind
    confidence: float = Field(ge=0, le=1)
    evidence_available: bool = True
    common_prefix_calls: int = Field(ge=0)
    baseline_sequence: int | None = None
    candidate_sequence: int | None = None
    baseline_fingerprint: str | None = Field(default=None, max_length=256)
    candidate_fingerprint: str | None = Field(default=None, max_length=256)
    baseline_events: tuple[str, ...] = ()
    candidate_events: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Call:
    """一个工具调用(语义动作):指纹取首个带参阶段。"""

    tool_name: str
    fingerprint: str
    start_sequence: int
    sequences: tuple[int, ...]


@dataclass(frozen=True)
class _Divergence:
    """第一次行为分歧;kind 只描述分歧形态,不代表一定错。"""

    kind: FirstErrorKind
    baseline_sequence: int | None
    candidate_sequence: int | None
    baseline_fingerprint: str | None
    candidate_fingerprint: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _FirstErrorSignal:
    """由 ProcessVerifier violation 提升的强证据 first error。"""

    kind: FirstErrorKind
    candidate_sequence: int
    confidence: float
    reasons: tuple[str, ...]


# 优先级数字越小越优先;用户固定:critical > 未恢复错误 > validation >
# compaction 重复 > premature > 普通行为分歧。
_FIRST_ERROR_RANK: dict[ProcessViolationType, tuple[int, FirstErrorKind]] = {
    ProcessViolationType.TEST_TAMPERING: (0, FirstErrorKind.PROCESS_VIOLATION),
    ProcessViolationType.TOOL_ERROR_NOT_RECOVERED: (
        1,
        FirstErrorKind.ERROR_RECOVERY,
    ),
    ProcessViolationType.VALIDATION_MISSING: (2, FirstErrorKind.VALIDATION),
    ProcessViolationType.CONTEXT_REGRESSION: (3, FirstErrorKind.CONTEXT),
    ProcessViolationType.PREMATURE_TERMINATION: (4, FirstErrorKind.TERMINATION),
    ProcessViolationType.REPEATED_TOOL_CALL: (5, FirstErrorKind.UNKNOWN),
}


def attribute_first_error(
    *,
    task: TaskSpec,
    candidate_result: TaskResult,
    baseline_result: TaskResult | None = None,
    baseline_evidence: Sequence[ProcessEvidence] = (),
    candidate_evidence: Sequence[ProcessEvidence] = (),
) -> FirstErrorAttribution | None:
    """在成对轨迹上定位第一次有因果意义的偏离。

    任一侧过程证据为空(旧格式/不可用轨迹)时显式返回
    ``evidence_available=False`` 的 attribution,不做归因——不要把
    「没测」误报成「candidate 插入/删除了调用」或 0.6 置信的错误。

    两条轨迹完全一致(调用级)且无 process violation 时返回 None。
    强证据(candidate 有 violation)confidence 1.0(baseline 也有同类则
    0.7);无 violation 时只有 baseline PASS → candidate FAIL 才给低
    置信候选(0.6)——PASS→PASS 的不同实现路径不是 first error,
    返回 None。
    """

    if not baseline_evidence or not candidate_evidence:
        missing = "baseline" if not baseline_evidence else "candidate"
        return FirstErrorAttribution(
            task_id=task.task_id,
            attempt=candidate_result.attempt,
            kind=FirstErrorKind.UNKNOWN,
            confidence=0.0,
            evidence_available=False,
            common_prefix_calls=0,
            reasons=(f"{missing} 侧过程证据为空(旧格式/不可用轨迹),无法做首错归因",),
        )

    baseline_calls = _call_sequence(baseline_evidence)
    candidate_calls = _call_sequence(candidate_evidence)
    prefix = _common_prefix(baseline_calls, candidate_calls)
    divergence = _first_divergence(baseline_calls, candidate_calls, prefix)

    verifier = ProcessVerifier()
    candidate_verification = verifier.verify(
        task=task,
        task_result=candidate_result,
        trace_events=(),
        evidence=candidate_evidence,
    )
    baseline_verification = None
    if baseline_result is not None:
        baseline_verification = verifier.verify(
            task=task,
            task_result=baseline_result,
            trace_events=(),
            evidence=baseline_evidence,
        )

    max_sequence = max((item.sequence for item in candidate_evidence), default=0)
    signal = _pick_first_error(
        candidate_verification,
        baseline_verification,
        max_sequence=max_sequence,
    )
    if signal is not None:
        candidate_start = signal.candidate_sequence
        if divergence is not None and divergence.candidate_sequence is not None:
            candidate_start = min(candidate_start, divergence.candidate_sequence)
        return FirstErrorAttribution(
            task_id=task.task_id,
            attempt=candidate_result.attempt,
            kind=signal.kind,
            confidence=signal.confidence,
            common_prefix_calls=prefix,
            baseline_sequence=(
                divergence.baseline_sequence if divergence is not None else None
            ),
            candidate_sequence=signal.candidate_sequence,
            baseline_fingerprint=(
                divergence.baseline_fingerprint if divergence is not None else None
            ),
            candidate_fingerprint=(
                divergence.candidate_fingerprint if divergence is not None else None
            ),
            baseline_events=_snippet(
                baseline_evidence,
                (
                    divergence.baseline_sequence
                    if divergence is not None and divergence.baseline_sequence
                    else 1
                ),
                4,
            ),
            candidate_events=_snippet(candidate_evidence, candidate_start, 6),
            reasons=signal.reasons,
        )

    # 无 process violation 的纯行为分歧:只有 baseline PASS → candidate
    # FAIL 时才给低置信候选(0.6);PASS→PASS 的不同实现路径不是
    # first error,返回 None——否则 harmless divergence 会污染
    # regression_probe 的回归语料。
    if divergence is None:
        return None
    if not (
        baseline_result is not None
        and baseline_result.verdict is TaskVerdict.PASSED
        and candidate_result.verdict is TaskVerdict.FAILED
    ):
        return None
    return FirstErrorAttribution(
        task_id=task.task_id,
        attempt=candidate_result.attempt,
        kind=divergence.kind,
        confidence=0.6,
        common_prefix_calls=prefix,
        baseline_sequence=divergence.baseline_sequence,
        candidate_sequence=divergence.candidate_sequence,
        baseline_fingerprint=divergence.baseline_fingerprint,
        candidate_fingerprint=divergence.candidate_fingerprint,
        baseline_events=_snippet(
            baseline_evidence, divergence.baseline_sequence or 1, 4
        ),
        candidate_events=_snippet(
            candidate_evidence, divergence.candidate_sequence or 1, 6
        ),
        reasons=(
            "无 process violation,但 baseline PASS → candidate FAIL 且存在行为分歧",
        ),
    )


def _call_sequence(evidence: Sequence[ProcessEvidence]) -> tuple[_Call, ...]:
    """把 ProcessEvidence 聚成调用序列(按 sequence 排序后的首次出现顺序)。

    聚合前必须先按 sequence 排序:调用方传入顺序可能被打乱,若按传入
    顺序聚合,同一组证据会得到不同的共同前缀与 first divergence。
    无 tool_call_id 的 evidence(validation/termination/compaction)不是
    语义动作,不参与对齐;它们仍参与 ProcessVerifier 的错误信号。
    """

    ordered = tuple(sorted(evidence, key=lambda item: item.sequence))
    by_call: dict[str, list[ProcessEvidence]] = {}
    order: list[str] = []
    for item in ordered:
        if item.tool_call_id is None:
            continue
        if item.tool_call_id not in by_call:
            by_call[item.tool_call_id] = []
            order.append(item.tool_call_id)
        by_call[item.tool_call_id].append(item)
    calls: list[_Call] = []
    for call_id in order:
        items = by_call[call_id]
        fingerprint = _call_fingerprint(items)
        tool_name = next((item.tool_name for item in items if item.tool_name), "")
        sequences = tuple(item.sequence for item in items)
        calls.append(
            _Call(
                tool_name=tool_name or "<no-tool>",
                fingerprint=fingerprint,
                start_sequence=sequences[0],
                sequences=sequences,
            )
        )
    return tuple(calls)


def _call_fingerprint(items: Sequence[ProcessEvidence]) -> str:
    """调用指纹取首个带参阶段(start/update);end 阶段无参数不可作比对。"""

    for item in items:
        if item.tool_phase in {ToolPhase.START, ToolPhase.UPDATE}:
            if item.tool_fingerprint:
                return item.tool_fingerprint
    return ""


def _common_prefix(baseline: tuple[_Call, ...], candidate: tuple[_Call, ...]) -> int:
    prefix = 0
    for baseline_call, candidate_call in zip(baseline, candidate):
        if _align_key(baseline_call) != _align_key(candidate_call):
            break
        prefix += 1
    return prefix


def _align_key(call: _Call) -> tuple[str, str]:
    return (call.tool_name, call.fingerprint or "<no-fp>")


def _first_divergence(
    baseline: tuple[_Call, ...],
    candidate: tuple[_Call, ...],
    prefix: int,
) -> _Divergence | None:
    """共同前缀结束处的第一次分歧;两侧都有内容才比较工具/指纹。"""

    baseline_call = baseline[prefix] if prefix < len(baseline) else None
    candidate_call = candidate[prefix] if prefix < len(candidate) else None
    if baseline_call is None and candidate_call is None:
        return None
    if baseline_call is not None and candidate_call is not None:
        if baseline_call.tool_name != candidate_call.tool_name:
            return _Divergence(
                kind=FirstErrorKind.TOOL_SELECTION,
                baseline_sequence=baseline_call.start_sequence,
                candidate_sequence=candidate_call.start_sequence,
                baseline_fingerprint=baseline_call.fingerprint or None,
                candidate_fingerprint=candidate_call.fingerprint or None,
                reasons=(
                    f"共同前缀后工具选择不同:baseline={baseline_call.tool_name}"
                    f" vs candidate={candidate_call.tool_name}",
                ),
            )
        return _Divergence(
            kind=FirstErrorKind.TOOL_ARGUMENT,
            baseline_sequence=baseline_call.start_sequence,
            candidate_sequence=candidate_call.start_sequence,
            baseline_fingerprint=baseline_call.fingerprint or None,
            candidate_fingerprint=candidate_call.fingerprint or None,
            reasons=("共同前缀后同工具但参数指纹不同",),
        )
    if baseline_call is None:
        return _Divergence(
            kind=FirstErrorKind.UNKNOWN,
            baseline_sequence=None,
            candidate_sequence=candidate_call.start_sequence,
            baseline_fingerprint=None,
            candidate_fingerprint=candidate_call.fingerprint or None,
            reasons=("candidate 在共同前缀后多出调用(插入)",),
        )
    return _Divergence(
        kind=FirstErrorKind.UNKNOWN,
        baseline_sequence=baseline_call.start_sequence,
        candidate_sequence=None,
        baseline_fingerprint=baseline_call.fingerprint or None,
        candidate_fingerprint=None,
        reasons=("candidate 在共同前缀后缺少调用(删除)",),
    )


def _pick_first_error(
    candidate: ProcessVerification,
    baseline: ProcessVerification | None,
    *,
    max_sequence: int,
) -> _FirstErrorSignal | None:
    """按固定优先级从 candidate violations 里选 first error。

    candidate_sequence 取该 violation 最早 evidence_offset;无 offset
    (如 validation_missing)退化为轨迹最大 sequence。
    """

    best: ProcessViolation | None = None
    best_key: tuple[int, int] | None = None
    for violation in candidate.violations:
        rank, _kind = _FIRST_ERROR_RANK.get(
            violation.violation_type, (6, FirstErrorKind.UNKNOWN)
        )
        earliest = (
            violation.evidence_offsets[0]
            if violation.evidence_offsets
            else max_sequence
        )
        key = (rank, earliest)
        if best_key is None or key < best_key:
            best_key = key
            best = violation
    if best is None:
        return None
    rank, kind = _FIRST_ERROR_RANK.get(best.violation_type, (6, FirstErrorKind.UNKNOWN))
    earliest = best.evidence_offsets[0] if best.evidence_offsets else max_sequence
    baseline_has_same = baseline is not None and any(
        violation.violation_type is best.violation_type
        for violation in baseline.violations
    )
    confidence = 0.7 if baseline_has_same else 1.0
    reasons = (f"ProcessVerifier 捕获 {best.violation_type.value}(优先级 {rank + 1})",)
    if baseline_has_same:
        reasons += ("baseline 也存在同类 violation,置信度降低",)
    return _FirstErrorSignal(
        kind=kind,
        candidate_sequence=earliest,
        confidence=confidence,
        reasons=reasons,
    )


def _snippet(
    evidence: Sequence[ProcessEvidence],
    start_sequence: int,
    count: int,
) -> tuple[str, ...]:
    """从指定 sequence 起取连续 count 条红acted 摘要行。"""

    ordered = tuple(sorted(evidence, key=lambda item: item.sequence))
    start_index = 0
    for index, item in enumerate(ordered):
        if item.sequence >= start_sequence:
            start_index = index
            break
    return tuple(_describe(item) for item in ordered[start_index : start_index + count])


def _describe(item: ProcessEvidence) -> str:
    """单条证据的可读摘要;不含路径或命令原文。

    验证命令通常同时带有工具名(如 pytest 调用),tool 分支同样要
    保留 ``validation`` 标记,不能因提前返回而丢。
    """

    if item.tool_name:
        parts = [str(item.sequence), item.tool_name]
        if item.tool_phase is not None:
            parts.append(item.tool_phase.value)
        if item.tool_phase is ToolPhase.END and item.is_error:
            parts.append("error=True")
        if item.tool_fingerprint and item.tool_phase in {
            ToolPhase.START,
            ToolPhase.UPDATE,
        }:
            parts.append(f"fp={item.tool_fingerprint[:8]}")
        if item.validation_command:
            parts.append("validation")
        return " ".join(parts)
    if item.termination is not None:
        return f"{item.sequence} termination={item.termination.value}"
    if item.compaction is not None:
        return f"{item.sequence} compaction={item.compaction.value}"
    if item.validation_command:
        return f"{item.sequence} validation"
    return f"{item.sequence} evidence"


__all__ = ["FirstErrorAttribution", "FirstErrorKind", "attribute_first_error"]
