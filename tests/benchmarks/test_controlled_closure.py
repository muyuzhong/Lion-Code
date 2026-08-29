"""Controlled Experiment Closure 单元测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from benchmarks.agent_e2e.artifact import CommitArtifact
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.controlled_runner import ControlledExperimentRunner
from benchmarks.agent_e2e.fixtures import (
    AGENT_CODE_SHA,
    EVALUATOR_CODE_SHA,
    make_task,
)
from benchmarks.agent_e2e.harbor_agent import LionInstalledAgent
from benchmarks.agent_e2e.harbor_runner import (
    HarborExecutionOutput,
    HarborExecutionRequest,
    HarborRoutineVerifierResult,
    HarborSingleTaskRunner,
)
from benchmarks.agent_e2e.harness_runner import (
    HarnessExecutionOutput,
    HarnessExecutionRequest,
)
from benchmarks.agent_e2e.models import (
    AdapterStatus,
    AgentRunSummary,
    Catalog,
    ExperimentManifest,
    ExperimentProfile,
    HarnessRecheckResult,
    InjectionEvidence,
    RequestedVariant,
    ResolvedVariant,
    TaskSpec,
    TrialExecutionStatus,
    VerifierOutcome,
    WorkerResult,
    WorkerStatus,
)
from benchmarks.agent_e2e.variant_injection import (
    PromptVariantMap,
    ToolPolicyVariantMap,
    VariantInjectionSpec,
    attach_injection_spec,
    resolve_injection,
    spec_from_manifest,
)
from benchmarks.agent_e2e.verified_runner import VerifiedExecutionRequest
from tests.benchmarks.test_agent_worker import _manifest, _task


def _spec() -> VariantInjectionSpec:
    prompt_fp = hashlib.sha256("受控提示词".encode()).hexdigest()
    tool_fp = hashlib.sha256(
        "\n".join(("read_file", "edit_file")).encode("utf-8")
    ).hexdigest()
    return VariantInjectionSpec(
        prompt_maps=(
            PromptVariantMap(
                prompt_version="prompt-v2",
                system_prompt="受控提示词",
                content_sha256=prompt_fp,
            ),
        ),
        tool_policy_maps=(
            ToolPolicyVariantMap(
                tool_policy_version="tools-v2",
                tool_names=("read_file", "edit_file"),
                content_sha256=tool_fp,
            ),
        ),
    )


class TestManifestSpecAttachment:
    def test_attach_and_read_round_trip(self) -> None:
        manifest = _manifest(_task())
        attached = attach_injection_spec(manifest, _spec())
        restored = spec_from_manifest(attached)
        assert restored == _spec()

    def test_original_manifest_unchanged(self) -> None:
        manifest = _manifest(_task())
        attach_injection_spec(manifest, _spec())
        assert spec_from_manifest(manifest) is None

    def test_missing_spec_returns_none(self) -> None:
        assert spec_from_manifest(_manifest(_task())) is None

    def test_attached_manifest_serializes(self) -> None:
        manifest = attach_injection_spec(_manifest(_task()), _spec())
        restored = ExperimentManifest.from_json(manifest.canonical_json())
        assert spec_from_manifest(restored) == _spec()


class TestInjectionEvidence:
    def test_resolution_carries_requested_and_resolved(self) -> None:
        from benchmarks.agent_e2e.models import ExperimentProfile

        profile = ExperimentProfile(
            profile_id="p1",
            model="m",
            provider="fake",
            prompt_version="prompt-v2",
            compression_version="compression-v1",
            tool_policy_version="tools-v2",
            seed=1,
            repeats=1,
            timeout_seconds=30,
            budget_usd=1,
            agent_code_sha="abcdef0",
            credential_env_vars=("K",),
        )
        resolution = resolve_injection(profile, _spec())
        assert resolution.resolved is True
        assert resolution.requested.prompt_version == "prompt-v2"
        assert resolution.requested.compression_version == "compression-v1"
        assert resolution.resolved_variant.prompt_hit is True
        assert resolution.resolved_variant.tool_policy_hit is True
        assert resolution.injection_fingerprint is not None

    def test_evidence_json_round_trip(self) -> None:
        evidence = InjectionEvidence(
            requested=RequestedVariant(prompt_version="prompt-v2"),
            resolved_variant=ResolvedVariant(prompt_hit=True),
            injection_fingerprint="f" * 64,
        )
        restored = InjectionEvidence.from_json(evidence.canonical_json())
        assert restored == evidence

    def test_requested_includes_compression_as_declared_only(self) -> None:
        from benchmarks.agent_e2e.models import ExperimentProfile

        profile = ExperimentProfile(
            profile_id="p1",
            model="m",
            provider="fake",
            prompt_version="prompt-v1",
            compression_version="compression-v9",
            tool_policy_version="tools-v1",
            seed=1,
            repeats=1,
            timeout_seconds=30,
            budget_usd=1,
            agent_code_sha="abcdef0",
            credential_env_vars=("K",),
        )
        resolution = resolve_injection(profile, VariantInjectionSpec())
        assert resolution.requested.compression_version == "compression-v9"
        assert resolution.injection_fingerprint is None


class TestHarborSourceFiles:
    def test_source_files_include_fidelity_modules(self) -> None:
        source_files = set(LionInstalledAgent._SOURCE_FILES)
        assert "evidence.py" in source_files
        assert "variant_injection.py" in source_files
        assert "worker_entrypoint.py" in source_files

    def test_source_files_are_importable_chain(self) -> None:
        # agent_worker 依赖 variant_injection,worker_entrypoint 依赖
        # evidence;两模块必须随 worker 一起进容器。
        source_files = set(LionInstalledAgent._SOURCE_FILES)
        for required in ("agent_worker.py", "models.py", "trace.py"):
            assert required in source_files


def _artifact(root: Path):
    from benchmarks.agent_e2e.artifact import CommitArtifact

    wheel = root / "lion_code.whl"
    wheel.write_bytes(b"wheel")
    return CommitArtifact(
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        wheel_path=wheel,
        wheel_sha256=hashlib.sha256(b"wheel").hexdigest(),
        wheel_size_bytes=5,
        source_tree_sha256="c" * 64,
        repository_fingerprint="d" * 64,
        python_version="3.12.10",
        platform="linux",
    )


class TestHarborVariantValidation:
    def test_request_variant_requires_spec(self, tmp_path: Path) -> None:
        request = HarborExecutionRequest(
            repository_root=tmp_path,
            artifact=_artifact(tmp_path),
            manifest=_manifest(_task()),
            task=_task(),
            output_dir=tmp_path / "out",
            request_variant=True,
        )
        runner = HarborSingleTaskRunner()
        result = runner.run(request)
        assert result.result is not None
        assert "injection spec" in result.result.reason

    def test_request_variant_with_manifest_spec_passes_validation(
        self, tmp_path: Path
    ) -> None:
        task = _task()
        manifest = attach_injection_spec(_manifest(task), _spec())
        request = HarborExecutionRequest(
            repository_root=tmp_path,
            artifact=_artifact(tmp_path),
            manifest=manifest,
            task=task,
            output_dir=tmp_path / "out",
            request_variant=True,
        )
        runner = HarborSingleTaskRunner()
        result = runner.run(request)
        # 校验通过后应继续走预检(缺少 harbor),不报 injection 错误。
        assert result.result is not None
        assert "injection spec" not in result.result.reason


def _pair_spec() -> VariantInjectionSpec:
    """覆盖两侧 prompt 版本的共享映射表(两侧内容不同)。"""

    baseline_prompt = "基线提示词"
    candidate_prompt = "候选提示词"
    return VariantInjectionSpec(
        prompt_maps=(
            PromptVariantMap(
                prompt_version="prompt-v1",
                system_prompt=baseline_prompt,
                content_sha256=hashlib.sha256(
                    baseline_prompt.encode("utf-8")
                ).hexdigest(),
            ),
            PromptVariantMap(
                prompt_version="prompt-v2",
                system_prompt=candidate_prompt,
                content_sha256=hashlib.sha256(
                    candidate_prompt.encode("utf-8")
                ).hexdigest(),
            ),
        )
    )


def _template() -> ExperimentManifest:
    """两侧共享的冻结模板:两个任务、prompt-v1 的 baseline profile。"""

    task_a = make_task(task_id="task-a", verifier_identity="hidden-v1")
    task_b = make_task(task_id="task-b", verifier_identity="hidden-v1")
    catalog = Catalog(catalog_id="runner", catalog_version="v1", tasks=(task_a, task_b))
    profile = ExperimentProfile(
        profile_id="baseline",
        model="fake-model",
        provider="fake",
        prompt_version="prompt-v1",
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=1,
        agent_code_sha=AGENT_CODE_SHA,
        credential_env_vars=("EVAL_API_KEY",),
    )
    return ExperimentManifest(
        run_id="template-run",
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha=EVALUATOR_CODE_SHA,
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task_a.task_id, task_b.task_id),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="offline-test",
    )


class _FakeVerifiedArtifactBuilder:
    """仅测试:确定性 CommitArtifact,与 Verified 主链的注入点一致。"""

    def build(self, commit_sha: str, output_dir: Path) -> CommitArtifact:
        wheel = output_dir / "lion_code-0.0.0-py3-none-any.whl"
        wheel.parent.mkdir(parents=True, exist_ok=True)
        wheel.write_bytes(b"wheel")
        return CommitArtifact(
            commit_sha=commit_sha,
            tree_sha="b" * 40,
            wheel_path=wheel,
            wheel_sha256=hashlib.sha256(b"wheel").hexdigest(),
            wheel_size_bytes=5,
            source_tree_sha256="c" * 64,
            repository_fingerprint="d" * 64,
            python_version="3.12.10",
            platform="linux",
        )


class _FakeVerifiedHarbor:
    """仅测试:Harbor 的确定性替身,按 manifest 解析注入并落盘证据。"""

    def __init__(self, outcomes: dict[str, bool]) -> None:
        self.outcomes = outcomes
        self.requests: list[HarborExecutionRequest] = []

    def run(self, request: HarborExecutionRequest) -> HarborExecutionOutput:
        self.requests.append(request)
        output_dir = request.output_dir
        patch_path = output_dir / "artifacts" / "lion.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_bytes = f"patch-{request.task.task_id}".encode()
        patch_path.write_bytes(patch_bytes)
        resolution = resolve_injection(
            request.manifest.profile,
            spec_from_manifest(request.manifest),
        )
        worker = WorkerResult(
            status=WorkerStatus.COMPLETED,
            agent_run=AgentRunSummary(
                final_text_digest=hashlib.sha256(b"done").hexdigest(),
                final_text_preview="done",
                stop_reason="completed",
                turns=1,
                wall_time_seconds=1,
                input_tokens=2,
                output_tokens=3,
                cache_read_tokens=0,
                cost_usd=0,
            ),
            patch_sha256=hashlib.sha256(patch_bytes).hexdigest(),
            patch_applied=True,
            injection_evidence=InjectionEvidence(
                requested=resolution.requested,
                resolved_variant=resolution.resolved_variant,
                injection_fingerprint=resolution.injection_fingerprint,
                prompt_sha256=resolution.prompt_sha256,
                tool_policy_sha256=resolution.tool_policy_sha256,
            ),
        )
        passed = self.outcomes.get(request.task.task_id, False)
        return HarborExecutionOutput(
            result=HarborRoutineVerifierResult(
                task_id=request.task.task_id,
                job_id=f"job-{request.task.task_id}",
                status=AdapterStatus.COMPLETED,
                execution_status=TrialExecutionStatus.COMPLETED,
                verifier_outcome=(
                    VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
                ),
                reward=1.0 if passed else 0.0,
                patch_sha256=worker.patch_sha256,
                patch_applied=True,
                output_digest="h" * 64,
                command_summary="fake Harbor verifier",
                wall_time_seconds=1.0,
            ),
            patch_path=patch_path,
            worker_result=worker,
        )


class _FakeVerifiedHarness:
    """仅测试:SWE-bench Harness 的确定性替身,按 task_id 给 resolved。"""

    def __init__(self, outcomes: dict[str, bool]) -> None:
        self.outcomes = outcomes

    def run(self, request: HarnessExecutionRequest) -> HarnessExecutionOutput:
        resolved = self.outcomes.get(request.instance_id, False)
        return HarnessExecutionOutput(
            result=HarnessRecheckResult(
                task_id=request.instance_id,
                status=AdapterStatus.COMPLETED,
                resolved=resolved,
                patch_sha256=request.patch_sha256,
                output_digest="f" * 64,
                evaluator_revision="swebench-5.0.1",
                image_digest="sha256:" + "b" * 64,
            )
        )


class TestControlledExperimentRunner:
    def test_build_manifests_freezes_two_runs(self) -> None:
        template = _template()
        candidate_profile = template.profile.model_copy(
            update={"profile_id": "candidate", "prompt_version": "prompt-v2"}
        )
        runner = ControlledExperimentRunner(injection_spec=_pair_spec())
        baseline, candidate = runner.build_manifests(
            template=template,
            baseline_profile=template.profile,
            candidate_profile=candidate_profile,
            baseline_run_id="run-baseline",
            candidate_run_id="run-candidate",
        )
        assert baseline.run_id == "run-baseline"
        assert candidate.run_id == "run-candidate"
        assert baseline.profile.prompt_version == "prompt-v1"
        assert candidate.profile.prompt_version == "prompt-v2"
        # 两侧挂载同一份映射表;模板本身不被修改。
        assert spec_from_manifest(template) is None
        assert spec_from_manifest(baseline) == _pair_spec()
        assert spec_from_manifest(candidate) == _pair_spec()

    def test_build_manifests_rejects_agent_code_change(self) -> None:
        template = _template()
        other_code = template.profile.model_copy(
            update={"profile_id": "other", "agent_code_sha": "deadbee"}
        )
        runner = ControlledExperimentRunner()
        with pytest.raises(ValueError, match="agent_code_sha"):
            runner.build_manifests(
                template=template,
                baseline_profile=template.profile,
                candidate_profile=other_code,
                baseline_run_id="run-baseline",
                candidate_run_id="run-candidate",
            )

    def test_run_pair_executes_both_sides_and_builds_controlled(
        self, tmp_path: Path
    ) -> None:
        template = _template()
        candidate_profile = template.profile.model_copy(
            update={"profile_id": "candidate", "prompt_version": "prompt-v2"}
        )
        runner = ControlledExperimentRunner(injection_spec=_pair_spec())
        baseline_manifest, candidate_manifest = runner.build_manifests(
            template=template,
            baseline_profile=template.profile,
            candidate_profile=candidate_profile,
            baseline_run_id="run-baseline",
            candidate_run_id="run-candidate",
        )
        tasks = tuple(
            make_task(task_id=task_id, verifier_identity="hidden-v1")
            for task_id in ("task-a", "task-b")
        )
        baseline_request = _verified_request(
            baseline_manifest, tasks[0], tmp_path / "verified"
        )
        candidate_request = _verified_request(
            candidate_manifest, tasks[0], tmp_path / "verified"
        )
        outcomes = {"task-a": False, "task-b": True}
        harbor = _FakeVerifiedHarbor(outcomes)
        experiment = runner.run_pair(
            baseline_request=baseline_request,
            candidate_request=candidate_request,
            tasks=tasks,
            artifact_builder=_FakeVerifiedArtifactBuilder(),
            harbor_runner=harbor,
            harness_runner=_FakeVerifiedHarness(outcomes),
        )
        # 全链路:runner → Verified 官方原语(artifact→Harbor→Harness)→
        # TaskResult+InjectionEvidence → run 级校验 → 配对判定。
        assert experiment.experiment_kind.value == "controlled"
        report = experiment.to_report()
        assert report.baseline_run_id == "run-baseline"
        assert report.candidate_run_id == "run-candidate"
        assert report.baseline_injection is not None
        assert report.candidate_injection is not None
        assert report.baseline_injection.result_count == 2
        assert report.candidate_injection.result_count == 2
        assert (
            report.baseline_injection.injection_fingerprint
            != report.candidate_injection.injection_fingerprint
        )
        assert report.counts.fail_to_fail == 1
        assert report.counts.pass_to_pass == 1
        # Verified 链把 worker 注入证据透传进 TaskResult.extensions。
        assert all(
            "injection_evidence" in result.extensions
            for result in (*experiment.baseline.results, *experiment.candidate.results)
        )
        # 两侧各执行了 2 个 Harbor 单题请求;manifest 带 spec 时声明受控。
        assert len(harbor.requests) == 4
        assert all(request.request_variant for request in harbor.requests)

    def test_run_pair_rejects_identical_profiles(self, tmp_path: Path) -> None:
        template = _template()
        runner = ControlledExperimentRunner()
        baseline, candidate = runner.build_manifests(
            template=template,
            baseline_profile=template.profile,
            candidate_profile=template.profile,
            baseline_run_id="run-baseline",
            candidate_run_id="run-candidate",
        )
        tasks = (make_task(task_id="task-a", verifier_identity="hidden-v1"),)
        with pytest.raises(ValueError, match="gate-controlled"):
            runner.run_pair(
                baseline_request=_verified_request(
                    baseline, tasks[0], tmp_path / "verified"
                ),
                candidate_request=_verified_request(
                    candidate, tasks[0], tmp_path / "verified"
                ),
                tasks=tasks,
            )

    def test_run_pair_rejects_missing_tasks(self, tmp_path: Path) -> None:
        template = _template()
        candidate_profile = template.profile.model_copy(
            update={"profile_id": "candidate", "prompt_version": "prompt-v2"}
        )
        runner = ControlledExperimentRunner(injection_spec=_pair_spec())
        baseline, candidate = runner.build_manifests(
            template=template,
            baseline_profile=template.profile,
            candidate_profile=candidate_profile,
            baseline_run_id="run-baseline",
            candidate_run_id="run-candidate",
        )
        partial_tasks = (make_task(task_id="task-a", verifier_identity="hidden-v1"),)
        with pytest.raises(ValueError, match="missing from the task list"):
            runner.run_pair(
                baseline_request=_verified_request(
                    baseline, partial_tasks[0], tmp_path / "verified"
                ),
                candidate_request=_verified_request(
                    candidate, partial_tasks[0], tmp_path / "verified"
                ),
                tasks=partial_tasks,
            )


def _verified_request(
    manifest: ExperimentManifest,
    task: TaskSpec,
    output_root: Path,
) -> VerifiedExecutionRequest:
    """构建 Verified 官方执行请求;task/output_dir 每单位由 runner 派生。"""

    return VerifiedExecutionRequest(
        repository_root=output_root,
        commit_sha=AGENT_CODE_SHA,
        manifest=manifest,
        task=task,
        output_dir=output_root,
        python_executable="python",
        harness_python="python",
    )
