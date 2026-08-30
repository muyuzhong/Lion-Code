"""失败片段最小化:把 FirstErrorAttribution 背后的证据裁成单事件不可再约简
的充分片段(1-minimal),作为 Evidence Regression Corpus 的回归样本。

V1 只做 deterministic slicing——不重跑模型、不复现 Agent 行为。裁剪
循环本身不感知 violation 结构,差异全部由 ``probe_holds`` 承载:内部
直接复用 ``ProcessVerifier``,对每个候选切片判定目标 violation 是否
仍成立。不同 violation 的充分条件天然不同(unrecovered error 需要
failed call + 同指纹 repeat;context regression 需要 compaction 边界;
test_tampering 只需 write tool + test/verifier scope),都由 verifier
规则表达,而不是靠「只按事件数裁剪」的启发式。

注意边界:本模块产出的片段只用于**检测规则回归**(同一 evidence 经同一
verifier 是否仍触发同一 violation),不代表 Harness 行为回归——它不执行
任何生产 Harness 逻辑。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .evidence import ProcessEvidence
from .models import TaskResult, TaskSpec
from .process_verifier import ProcessVerifier, ProcessViolationType

# probe 签名:给定切片上目标 violation 是否仍存在。
Probe = Callable[
    [ProcessViolationType, Sequence[ProcessEvidence], TaskSpec, TaskResult],
    bool,
]


def probe_holds(
    violation_type: ProcessViolationType,
    evidence: Sequence[ProcessEvidence],
    task: TaskSpec,
    task_result: TaskResult,
    *,
    verifier: ProcessVerifier | None = None,
) -> bool:
    """给定证据切片上,目标 violation 是否仍存在(纯确定性)。

    空 evidence 恒为 False:空切片降级为 ``EVIDENCE_UNAVAILABLE``,不是
    任何 violation。内部直接复用 ``ProcessVerifier.verify``,不重复实现
    任何规则。
    """

    if not evidence:
        return False
    active = verifier or ProcessVerifier()
    verification = active.verify(
        task=task,
        task_result=task_result,
        trace_events=(),
        evidence=evidence,
    )
    return any(
        violation.violation_type is violation_type
        for violation in verification.violations
    )


def minimize_failure_evidence(
    *,
    violation_type: ProcessViolationType,
    task: TaskSpec,
    task_result: TaskResult,
    evidence: Sequence[ProcessEvidence],
    probe: Probe | None = None,
    verifier: ProcessVerifier | None = None,
) -> tuple[ProcessEvidence, ...]:
    """把证据裁成单事件不可再约简的充分片段(1-minimal sufficient fragment)。

    greedy 逐事件裁剪:每轮从首事件开始,删除单个事件后 probe 仍成立
    则接受删除并从头重来;一整轮没有任何删除即收敛。结果与事件顺序
    无关(先按 sequence 排序),同输入必得同输出。

    收敛保证的是 **1-minimal**(删除最终片段中任意一个事件,violation
    都不再成立),不是全局最短;不为此引入组合搜索或复杂 delta debugging。

    初始切片不满足 probe 时抛 ``ValueError``——本函数只应对已经成立的
    violation 调用,否则「裁剪」没有意义。
    """

    active_probe = probe or (
        lambda vt, sl, tk, tr: probe_holds(vt, sl, tk, tr, verifier=verifier)
    )
    current = tuple(sorted(evidence, key=lambda item: item.sequence))
    if not active_probe(violation_type, current, task, task_result):
        raise ValueError(
            "minimize_failure_evidence 只接受已成立的目标 violation;"
            "初始证据切片不满足 probe_holds"
        )
    while True:
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1 :]
            if active_probe(violation_type, candidate, task, task_result):
                current = candidate
                break
        else:
            return current


__all__ = ["Probe", "minimize_failure_evidence", "probe_holds"]
