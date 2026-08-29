"""受控实验的正式 host 工作流:共享映射表 + 两个 profile → 两次冻结 run → 配对实验。

受控实验复用现有 Verified 官方执行原语 ``run_verified_evaluation``
(artifact → Harbor → SWE-bench Harness),不再沿 foundation 的
``SingleTaskOrchestrator``/``ContainerBackend`` 开第二条执行链。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from .experiment import (
    ChangeKind,
    HarnessVariant,
    PairedExperiment,
    PairedExperimentError,
)
from .models import (
    EvaluationReport,
    ExperimentManifest,
    ExperimentProfile,
    TaskResult,
    TaskSpec,
)
from .report import build_report
from .variant_injection import VariantInjectionSpec, attach_injection_spec
from .verified_runner import VerifiedExecutionRequest, run_verified_evaluation


class ControlledExperimentRunner:
    """受控实验的唯一正式入口。

    ``build_manifests`` 从同一个冻结模板派生两侧 manifest(只替换
    profile 并挂载共享映射表);``run_pair`` 经 Verified 官方执行链跑完
    两侧全部 task×attempt 后交给 ``PairedExperiment`` 判定因果语义。
    """

    def __init__(self, *, injection_spec: VariantInjectionSpec | None = None) -> None:
        self.injection_spec = injection_spec

    def build_manifests(
        self,
        *,
        template: ExperimentManifest,
        baseline_profile: ExperimentProfile,
        candidate_profile: ExperimentProfile,
        baseline_run_id: str,
        candidate_run_id: str,
    ) -> tuple[ExperimentManifest, ExperimentManifest]:
        """从冻结模板生成两侧 manifest;模板本身不被修改。

        profile 与模板的 agent_code_sha / seed / repeats 等不变量不一致
        时由 manifest 校验器立即拒绝(冻结输入,不产生半成品)。
        """

        baseline = self._with_profile(template, baseline_profile, baseline_run_id)
        candidate = self._with_profile(template, candidate_profile, candidate_run_id)
        return baseline, candidate

    def run_pair(
        self,
        *,
        baseline_request: VerifiedExecutionRequest,
        candidate_request: VerifiedExecutionRequest,
        tasks: Sequence[TaskSpec],
        artifact_builder: Any | None = None,
        harbor_runner: Any | None = None,
        harness_runner: Any | None = None,
    ) -> PairedExperiment:
        """经 Verified 官方执行链跑两侧 run 并构建配对实验。

        两个请求分别携带 baseline/candidate 冻结 manifest 与共享 host
        上下文(commit / 可执行文件 / 输出根目录);每个 task×attempt
        派生一个 VerifiedExecutionRequest 交给 ``run_verified_evaluation``,
        失败即抛出,不做半成品配对。
        """

        _validate_execution_context(baseline_request, candidate_request)
        changes = _declared_changes(
            baseline_request.manifest, candidate_request.manifest
        )
        if not changes:
            raise PairedExperimentError(
                "Candidate does not change a gate-controlled profile version"
            )
        baseline_report = _execute_verified_run(
            baseline_request,
            tasks=tasks,
            artifact_builder=artifact_builder,
            harbor_runner=harbor_runner,
            harness_runner=harness_runner,
        )
        candidate_report = _execute_verified_run(
            candidate_request,
            tasks=tasks,
            artifact_builder=artifact_builder,
            harbor_runner=harbor_runner,
            harness_runner=harness_runner,
        )
        return PairedExperiment.build(baseline_report, candidate_report, changes)

    def _with_profile(
        self,
        template: ExperimentManifest,
        profile: ExperimentProfile,
        run_id: str,
    ) -> ExperimentManifest:
        # 用构造器重建(而非 model_copy)以重新触发冻结不变量校验:
        # agent_code_sha / seed 等与模板不一致时立即失败,不产生半成品。
        fields = template.model_dump()
        fields.update(
            run_id=run_id,
            profile=profile,
            profile_fingerprint=profile.fingerprint(),
            seed=profile.seed,
            repeats=profile.repeats,
            timeout_seconds=profile.timeout_seconds,
            budget_usd=profile.budget_usd,
        )
        manifest = ExperimentManifest(**fields)
        if self.injection_spec is not None:
            manifest = attach_injection_spec(manifest, self.injection_spec)
        return manifest


def _execute_verified_run(
    request: VerifiedExecutionRequest,
    *,
    tasks: Sequence[TaskSpec],
    artifact_builder: Any | None,
    harbor_runner: Any | None,
    harness_runner: Any | None,
) -> EvaluationReport:
    """顺序执行一次 run 冻结的全部 task×attempt 并汇总为正式报告。

    Verified 官方执行原语要求 ``repeats=1``(单题单次),配对实验的
    ``(task_id, attempt)`` 维度由 task_id 提供。
    """

    if request.manifest.repeats != 1:
        raise PairedExperimentError("Verified official execution requires repeats=1")
    tasks_by_id = {task.task_id: task for task in tasks}
    missing = set(request.manifest.task_ids) - set(tasks_by_id)
    if missing:
        raise PairedExperimentError(
            "Manifest tasks are missing from the task list: "
            + ", ".join(sorted(missing))
        )
    results: list[TaskResult] = []
    for task_id in request.manifest.task_ids:
        unit_request = replace(
            request,
            task=tasks_by_id[task_id],
            output_dir=(
                request.output_dir / request.manifest.run_id / task_id / "attempt-1"
            ),
        )
        output = run_verified_evaluation(
            unit_request,
            artifact_builder=artifact_builder,
            harbor_runner=harbor_runner,
            harness_runner=harness_runner,
        )
        results.append(output.report.task_result)
    return build_report(manifest=request.manifest, results=tuple(results))


def _declared_changes(
    baseline: ExperimentManifest,
    candidate: ExperimentManifest,
) -> tuple[ChangeKind, ...]:
    """从两侧 profile 的实际版本差异推导声明变更(两侧变化面即声明面)。"""

    baseline_variant = HarnessVariant.from_profile(
        baseline.profile, variant_id="baseline"
    )
    candidate_variant = HarnessVariant.from_profile(
        candidate.profile, variant_id="candidate"
    )
    return baseline_variant.change_kinds(candidate_variant)


# 受控实验必须逐项一致的宿主执行输入:manifest 可比性只约束声明面,
# 这些字段漂移会让「同 code_sha + 合法证据」掩盖「执行输入不同」的假因果。
_EXECUTION_CONTEXT_FIELDS = (
    "commit_sha",
    "repository_root",
    "python_executable",
    "harness_python",
    "harbor_executable",
)


def _validate_execution_context(
    baseline_request: VerifiedExecutionRequest,
    candidate_request: VerifiedExecutionRequest,
) -> None:
    """两侧宿主执行上下文必须完全一致,否则不做配对实验。"""

    for field_name in _EXECUTION_CONTEXT_FIELDS:
        if getattr(baseline_request, field_name) != getattr(
            candidate_request, field_name
        ):
            raise PairedExperimentError(
                "Execution context differs between baseline and candidate: "
                + field_name
            )


__all__ = ["ControlledExperimentRunner"]
