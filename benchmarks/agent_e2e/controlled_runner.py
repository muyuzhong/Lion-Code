"""受控实验的正式 host 工作流:共享映射表 + 两个 profile → 两次冻结 run → 配对实验。

此前注入映射表只能「手工拼装」attach_injection_spec 与 manifest,评测
系统本身无法发起一场受控实验;本模块把这条链路收成一个入口。
"""

from __future__ import annotations

from collections.abc import Sequence

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
from .orchestrator import SingleTaskOrchestrator
from .report import build_report
from .variant_injection import VariantInjectionSpec, attach_injection_spec


class ControlledExperimentRunner:
    """受控实验的唯一正式入口。

    ``build_manifests`` 从同一个冻结模板派生两侧 manifest(只替换
    profile 并挂载共享映射表);``run_pair`` 正式执行两侧全部
    task×attempt 后交给 ``PairedExperiment`` 判定因果语义。
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

    async def run_pair(
        self,
        *,
        orchestrator: SingleTaskOrchestrator,
        baseline_manifest: ExperimentManifest,
        candidate_manifest: ExperimentManifest,
        tasks: Sequence[TaskSpec],
    ) -> PairedExperiment:
        """正式执行两侧 run 并构建配对实验(失败即抛出,不做半成品)。"""

        changes = _declared_changes(baseline_manifest, candidate_manifest)
        if not changes:
            raise PairedExperimentError(
                "Candidate does not change a gate-controlled profile version"
            )
        baseline_report = await _execute_run(orchestrator, baseline_manifest, tasks)
        candidate_report = await _execute_run(orchestrator, candidate_manifest, tasks)
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


async def _execute_run(
    orchestrator: SingleTaskOrchestrator,
    manifest: ExperimentManifest,
    tasks: Sequence[TaskSpec],
) -> EvaluationReport:
    """顺序执行 manifest 冻结的全部 task×attempt 并汇总为正式报告。"""

    tasks_by_id = {task.task_id: task for task in tasks}
    missing = set(manifest.task_ids) - set(tasks_by_id)
    if missing:
        raise PairedExperimentError(
            "Manifest tasks are missing from the task list: "
            + ", ".join(sorted(missing))
        )
    results: list[TaskResult] = []
    for task_id in manifest.task_ids:
        for attempt in range(1, manifest.repeats + 1):
            results.append(
                await orchestrator.run_task(
                    manifest=manifest,
                    task=tasks_by_id[task_id],
                    attempt=attempt,
                )
            )
    return build_report(manifest=manifest, results=tuple(results))


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


__all__ = ["ControlledExperimentRunner"]
