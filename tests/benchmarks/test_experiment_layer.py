"""配对实验层单元测试:HarnessVariant / PairedExperiment / PairedTrial。"""

from __future__ import annotations

import pytest

from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.experiment import (
    ChangeKind,
    HarnessVariant,
    PairedExperiment,
    PairedExperimentError,
    PairedExperimentReport,
    PairedTrial,
    PairedTrialOutcome,
)
from benchmarks.agent_e2e.models import (
    AgentRunSummary,
    Catalog,
    EvaluationReport,
    ExperimentManifest,
    ExperimentProfile,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)
from benchmarks.agent_e2e.report import build_report


def _task(task_id: str) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="修复公开问题。",
        public_setup=("python -m pip install -e .",),
        public_validation_commands=("python -m pytest -q",),
        verifier_identity="hidden-v1",
        gold_evidence_hash="a" * 64,
        difficulty=2,
        involved_files=("lion_code/meta_agent.py",),
    )


def _result(
    task_id: str,
    *,
    attempt: int = 1,
    passed: bool,
    stop_reason: str = "completed",
) -> TaskResult:
    outcome = VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
    verdict = TaskVerdict.PASSED if passed else TaskVerdict.FAILED
    return TaskResult(
        task_id=task_id,
        attempt=attempt,
        verdict=verdict,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256="b" * 64,
        agent_run=AgentRunSummary(
            final_text_digest="c" * 64,
            stop_reason=stop_reason,
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


def _report(
    run_id: str,
    outcomes: tuple[bool, ...],
    *,
    prompt_version: str,
    compression_version: str = "compression-v1",
    model: str = "fake-model",
    catalog_id: str = "pair-fixture",
) -> EvaluationReport:
    tasks = tuple(_task(f"task-{index}") for index in range(1, len(outcomes) + 1))
    catalog = Catalog(catalog_id=catalog_id, catalog_version="v1", tasks=tasks)
    profile = ExperimentProfile(
        profile_id=f"profile-{prompt_version}",
        model=model,
        provider="fake",
        prompt_version=prompt_version,
        compression_version=compression_version,
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=1,
        agent_code_sha="abcdef0",
        credential_env_vars=("EVAL_API_KEY",),
    )
    manifest = ExperimentManifest(
        run_id=run_id,
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha="1234567",
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=tuple(task.task_id for task in tasks),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="linux-amd64",
        agent_image_digest="sha256:agent",
        verifier_image_digest="sha256:verifier",
    )
    return build_report(
        manifest=manifest,
        results=tuple(
            _result(task.task_id, passed=passed)
            for task, passed in zip(tasks, outcomes, strict=True)
        ),
    )


def _baseline() -> EvaluationReport:
    return _report(
        "run-baseline",
        (True, False, True, False),
        prompt_version="prompt-v1",
    )


def _candidate() -> EvaluationReport:
    return _report(
        "run-candidate",
        (False, True, True, False),
        prompt_version="prompt-v2",
    )


class TestHarnessVariant:
    def test_from_profile_extracts_changeable_fields(self) -> None:
        profile = _baseline().manifest.profile
        variant = HarnessVariant.from_profile(profile, variant_id="baseline")
        assert variant.variant_id == "baseline"
        assert variant.prompt_version == "prompt-v1"
        assert variant.compression_version == "compression-v1"
        assert variant.tool_policy_version == "tools-v1"

    def test_fingerprint_stable(self) -> None:
        profile = _baseline().manifest.profile
        first = HarnessVariant.from_profile(profile, variant_id="baseline")
        second = HarnessVariant.from_profile(profile, variant_id="baseline")
        assert first.fingerprint() == second.fingerprint()

    def test_change_kinds_maps_actual_differences(self) -> None:
        baseline = _baseline().manifest.profile
        candidate = _candidate().manifest.profile
        base_variant = HarnessVariant.from_profile(baseline, variant_id="baseline")
        cand_variant = HarnessVariant.from_profile(candidate, variant_id="candidate")
        assert cand_variant.change_kinds(base_variant) == (ChangeKind.PROMPT,)

    def test_change_kinds_empty_when_identical(self) -> None:
        profile = _baseline().manifest.profile
        variant = HarnessVariant.from_profile(profile, variant_id="x")
        assert variant.change_kinds(variant) == ()


class TestPairedTrialOutcome:
    def _trial(
        self,
        *,
        baseline_passed: bool,
        candidate_passed: bool,
    ) -> PairedTrial:
        return PairedTrial(
            task_id="task-1",
            attempt=1,
            baseline_result=_result("task-1", passed=baseline_passed),
            candidate_result=_result("task-1", passed=candidate_passed),
            outcome_delta=PairedExperiment.build(
                _report("r1", (baseline_passed,), prompt_version="p1"),
                _report("r2", (candidate_passed,), prompt_version="p2"),
                [ChangeKind.PROMPT],
            )
            .trials[0]
            .outcome_delta,
        )

    def test_winning_and_losing_deltas(self) -> None:
        assert (
            self._trial(baseline_passed=False, candidate_passed=True).outcome_delta
            is PairedTrialOutcome.FAIL_TO_PASS
        )
        assert (
            self._trial(baseline_passed=True, candidate_passed=False).outcome_delta
            is PairedTrialOutcome.PASS_TO_FAIL
        )
        assert (
            self._trial(baseline_passed=True, candidate_passed=True).outcome_delta
            is PairedTrialOutcome.PASS_TO_PASS
        )
        assert (
            self._trial(baseline_passed=False, candidate_passed=False).outcome_delta
            is PairedTrialOutcome.FAIL_TO_FAIL
        )

    def test_incomparable_pair_requires_invalid_delta(self) -> None:
        blocked = TaskResult(
            task_id="task-1",
            attempt=1,
            verdict=TaskVerdict.BLOCKED,
            validity=ResultValidity.BLOCKED,
            official=False,
        )
        with pytest.raises(ValueError):
            PairedTrial(
                task_id="task-1",
                attempt=1,
                baseline_result=blocked,
                candidate_result=_result("task-1", passed=True),
                outcome_delta=PairedTrialOutcome.PASS_TO_PASS,
            )
        trial = PairedTrial(
            task_id="task-1",
            attempt=1,
            baseline_result=blocked,
            candidate_result=_result("task-1", passed=True),
            outcome_delta=PairedTrialOutcome.INVALID,
        )
        assert trial.outcome_delta is PairedTrialOutcome.INVALID

    def test_trial_key_must_match_results(self) -> None:
        with pytest.raises(ValueError):
            PairedTrial(
                task_id="task-other",
                attempt=1,
                baseline_result=_result("task-1", passed=True),
                candidate_result=_result("task-1", passed=True),
                outcome_delta=PairedTrialOutcome.PASS_TO_PASS,
            )


class TestPairedExperimentBuild:
    def test_build_pairs_by_task_and_attempt(self) -> None:
        experiment = PairedExperiment.build(
            _baseline(),
            _candidate(),
            [ChangeKind.PROMPT],
        )
        assert [trial.task_id for trial in experiment.trials] == [
            "task-1",
            "task-2",
            "task-3",
            "task-4",
        ]
        assert all(trial.attempt == 1 for trial in experiment.trials)

    def test_build_rejects_same_run_id(self) -> None:
        report = _baseline()
        with pytest.raises(PairedExperimentError, match="distinct run IDs"):
            PairedExperiment.build(report, report, [ChangeKind.PROMPT])

    def test_build_rejects_catalog_mismatch(self) -> None:
        other = _report(
            "run-candidate",
            (False, True, True, False),
            prompt_version="prompt-v2",
            catalog_id="other-catalog",
        )
        with pytest.raises(PairedExperimentError, match="Catalog lock field differs"):
            PairedExperiment.build(_baseline(), other, [ChangeKind.PROMPT])

    def test_build_rejects_profile_invariant_mismatch(self) -> None:
        other = _report(
            "run-candidate",
            (False, True, True, False),
            prompt_version="prompt-v2",
            model="other-model",
        )
        with pytest.raises(
            PairedExperimentError, match="Profile invariant field differs: model"
        ):
            PairedExperiment.build(_baseline(), other, [ChangeKind.PROMPT])

    def test_build_rejects_declaration_mismatch(self) -> None:
        other = _report(
            "run-candidate",
            (False, True, True, False),
            prompt_version="prompt-v1",
            compression_version="compression-v2",
        )
        with pytest.raises(PairedExperimentError, match="Declared change kinds"):
            PairedExperiment.build(_baseline(), other, [ChangeKind.PROMPT])

    def test_build_rejects_no_actual_change(self) -> None:
        other = _report(
            "run-candidate", (True, False, True, False), prompt_version="prompt-v1"
        )
        with pytest.raises(
            PairedExperimentError, match="does not change a gate-controlled"
        ):
            PairedExperiment.build(_baseline(), other, [ChangeKind.PROMPT])

    def test_build_rejects_empty_declaration(self) -> None:
        with pytest.raises(PairedExperimentError, match="must be declared"):
            PairedExperiment.build(_baseline(), _candidate(), [])

    def test_build_rejects_incomplete_task_coverage(self) -> None:
        # 与 baseline 相同的 catalog/task 集,但只提供部分结果。
        baseline = _baseline()
        partial_manifest = baseline.manifest.model_copy(
            update={"run_id": "run-candidate"}
        )
        partial = build_report(
            manifest=partial_manifest,
            results=baseline.results[:2],
        )
        with pytest.raises(PairedExperimentError, match="cover every frozen task"):
            PairedExperiment.build(baseline, partial, [ChangeKind.PROMPT])

    def test_build_rejects_attempt_misalignment(self) -> None:
        tasks = tuple(_task(f"task-{index}") for index in range(1, 3))
        catalog = Catalog(catalog_id="pair-fixture", catalog_version="v1", tasks=tasks)
        profile = ExperimentProfile(
            profile_id="profile-p2",
            model="fake-model",
            provider="fake",
            prompt_version="prompt-v2",
            compression_version="compression-v1",
            tool_policy_version="tools-v1",
            seed=7,
            repeats=2,
            timeout_seconds=30,
            budget_usd=1,
            agent_code_sha="abcdef0",
            credential_env_vars=("EVAL_API_KEY",),
        )
        manifest = ExperimentManifest(
            run_id="run-baseline",
            agent_code_sha=profile.agent_code_sha,
            evaluator_code_sha="1234567",
            catalog=freeze_catalog(catalog),
            profile=profile,
            profile_fingerprint=profile.fingerprint(),
            task_ids=tuple(task.task_id for task in tasks),
            seed=profile.seed,
            repeats=profile.repeats,
            timeout_seconds=profile.timeout_seconds,
            budget_usd=profile.budget_usd,
            platform="linux-amd64",
            agent_image_digest="sha256:agent",
            verifier_image_digest="sha256:verifier",
        )
        baseline = build_report(
            manifest=manifest,
            results=(
                _result("task-1", attempt=1, passed=True),
                _result("task-1", attempt=2, passed=True),
                _result("task-2", attempt=1, passed=False),
                _result("task-2", attempt=2, passed=False),
            ),
        )
        misaligned_manifest = manifest.model_copy(update={"run_id": "run-candidate"})
        misaligned = build_report(
            manifest=misaligned_manifest,
            results=(
                _result("task-1", attempt=1, passed=False),
                _result("task-1", attempt=3, passed=True),
                _result("task-2", attempt=1, passed=False),
                _result("task-2", attempt=2, passed=True),
            ),
        )
        with pytest.raises(PairedExperimentError, match="cover every frozen task"):
            PairedExperiment.build(baseline, misaligned, [ChangeKind.PROMPT])


class TestPairedExperimentReport:
    def test_counts_match_four_grid(self) -> None:
        experiment = PairedExperiment.build(
            _baseline(),
            _candidate(),
            [ChangeKind.PROMPT],
        )
        report = experiment.to_report()
        assert report.counts.fail_to_pass == 1  # task-2
        assert report.counts.pass_to_fail == 1  # task-1
        assert report.counts.pass_to_pass == 1  # task-3
        assert report.counts.fail_to_fail == 1  # task-4
        assert report.counts.invalid == 0
        assert report.baseline_run_id == "run-baseline"
        assert report.candidate_run_id == "run-candidate"
        assert report.declared_changes == (ChangeKind.PROMPT,)
        assert len(report.comparability_fingerprint) == 64

    def test_json_round_trip(self) -> None:
        experiment = PairedExperiment.build(
            _baseline(),
            _candidate(),
            [ChangeKind.PROMPT],
        )
        report = experiment.to_report()
        restored = PairedExperimentReport.from_json(report.canonical_json())
        assert restored == report

    def test_fingerprint_stable_across_builds(self) -> None:
        first = PairedExperiment.build(_baseline(), _candidate(), [ChangeKind.PROMPT])
        second = PairedExperiment.build(_baseline(), _candidate(), [ChangeKind.PROMPT])
        assert first.comparability_fingerprint == second.comparability_fingerprint

    def test_render_markdown_lists_four_grid(self) -> None:
        report = PairedExperiment.build(
            _baseline(),
            _candidate(),
            [ChangeKind.PROMPT],
        ).to_report()
        text = report.render_markdown()
        assert "fail→pass" in text
        assert "run-baseline" in text
        assert "run-candidate" in text
