"""Verified 执行链的产物、patch、外部 runner 与官方归一化边界测试。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.benchmarks.fixtures.verified_task_1 import (
    AGENT_CODE_SHA,
    EVALUATOR_CODE_SHA,
    make_task,
)
from benchmarks.agent_e2e.artifact import CommitArtifact, CommitArtifactBuilder
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.harbor_runner import (
    HARBOR_AGENT_IMPORT_PATH,
    HARBOR_DATASET,
    HarborExecutionRequest,
    HarborSingleTaskRunner,
    _read_trial_output,
)
from benchmarks.agent_e2e.harness_runner import (
    SWEBENCH_DATASET,
    SWEBENCH_EVALUATOR_REVISION,
    HarnessExecutionRequest,
    OfficialSWEbenchHarnessRunner,
    _parse_official_report,
)
from benchmarks.agent_e2e.models import (
    AdapterStatus,
    ExperimentManifest,
    ExperimentProfile,
    FailureSource,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifierOutcome,
)
from benchmarks.agent_e2e.verified_runner import (
    VerifiedExecutionRequest,
    run_verified_evaluation,
)
from benchmarks.agent_e2e.worker_entrypoint import export_git_patch


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _git_repository(root: Path) -> str:
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Verified tests")
    (root / "tracked.txt").write_text("committed\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "--quiet", "-m", "initial")
    return _git(root, "rev-parse", "HEAD")


def _task() -> TaskSpec:
    return make_task(extensions={"harbor_task_name": "swebench-task-1"})


def _manifest(task: TaskSpec, *, budget_usd: float = 1.0) -> ExperimentManifest:
    profile = ExperimentProfile(
        profile_id="verified-online",
        model="test-model",
        provider="test-provider",
        prompt_version="prompt-v1",
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=budget_usd,
        agent_code_sha=AGENT_CODE_SHA,
        credential_env_vars=("TEST_PROVIDER_KEY",) if budget_usd else (),
    )
    from benchmarks.agent_e2e.models import Catalog

    catalog = Catalog(catalog_id="verified", catalog_version="v1", tasks=(task,))
    return ExperimentManifest(
        run_id="verified-run-1",
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha=EVALUATOR_CODE_SHA,
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="linux-docker",
        verifier_image_digest="sha256:" + "b" * 64,
    )


def _artifact(root: Path) -> CommitArtifact:
    wheel = root / "artifacts" / "lion_code.whl"
    wheel.parent.mkdir(parents=True, exist_ok=True)
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


class TestVerifiedExecutionChain(unittest.TestCase):
    def test_commit_artifact_uses_git_tree_and_stable_wheel_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commit = _git_repository(root)
            (root / "dirty.txt").write_text("must not ship\n", encoding="utf-8")

            def fake_build_wheel(source_root: Path, wheel_root: Path) -> None:
                names = sorted(
                    path.relative_to(source_root).as_posix()
                    for path in source_root.rglob("*")
                    if path.is_file()
                )
                wheel_path = wheel_root / "lion_code-0.0.0-py3-none-any.whl"
                with zipfile.ZipFile(wheel_path, "w") as archive:
                    archive.writestr("source-list.txt", "\n".join(names))

            builder = CommitArtifactBuilder(
                root,
                python_executable=sys.executable,
                staging_root=root / "staging",
            )
            with patch.object(builder, "_build_wheel", side_effect=fake_build_wheel):
                first = builder.build(commit, root / "out-1")
                second = builder.build(commit, root / "out-2")

            self.assertEqual(first.commit_sha, second.commit_sha)
            self.assertEqual(first.source_tree_sha256, second.source_tree_sha256)
            self.assertEqual(first.wheel_sha256, second.wheel_sha256)
            self.assertFalse((root / "staging").exists())
            with zipfile.ZipFile(first.wheel_path) as archive:
                source_list = archive.read("source-list.txt").decode()
            self.assertIn("tracked.txt", source_list)
            self.assertNotIn("dirty.txt", source_list)

    def test_export_git_patch_contains_tracked_and_untracked_without_host_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git_repository(root)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            (root / "new file.txt").write_text("new\n", encoding="utf-8")
            (root / "logs").mkdir()
            (root / "logs" / "result.json").write_text("output\n", encoding="utf-8")
            destination = root / "logs" / "lion.patch"

            patch_sha, applied = export_git_patch(root, destination)

            patch = destination.read_bytes()
            self.assertTrue(applied)
            self.assertEqual(patch_sha, hashlib.sha256(patch).hexdigest())
            self.assertIn(b"tracked.txt", patch)
            self.assertIn(b"new file.txt", patch)
            self.assertNotIn(b"result.json", patch)
            self.assertNotIn(str(root).encode(), patch)

    def test_harbor_command_is_pinned_and_does_not_contain_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _task()
            manifest = _manifest(task)
            request = HarborExecutionRequest(
                repository_root=root,
                artifact=_artifact(root),
                manifest=manifest,
                task=task,
                output_dir=root / "output",
            )
            command = HarborSingleTaskRunner().build_command(
                request, root / "output" / ".harbor-run" / manifest.run_id
            )
            rendered = " ".join(command)

            self.assertEqual(command[:2], ["harbor", "run"])
            self.assertIn(HARBOR_DATASET, command)
            self.assertIn(HARBOR_AGENT_IMPORT_PATH, command)
            self.assertIn("--n-tasks", command)
            self.assertIn("--n-attempts", command)
            self.assertIn("--n-concurrent", command)
            self.assertNotIn("super-secret", rendered)
            self.assertNotIn(str(root), rendered)

    def test_harbor_trial_result_is_normalized_and_patch_is_controlled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _task()
            manifest = _manifest(task)
            request = HarborExecutionRequest(
                repository_root=root,
                artifact=_artifact(root),
                manifest=manifest,
                task=task,
                output_dir=root / "output",
            )
            job_root = root / "job"
            trial_root = job_root / "trial"
            trial_root.mkdir(parents=True)
            patch_path = trial_root / "lion.patch"
            patch_path.write_bytes(b"diff --git a/tracked.txt b/tracked.txt\n")
            (trial_root / "result.json").write_text(
                json.dumps(
                    {
                        "task_name": "swebench-task-1",
                        "trial_name": "api_key=secret",
                        "verifier_result": {"rewards": {"reward": 1}},
                    }
                ),
                encoding="utf-8",
            )

            output = _read_trial_output(request, job_root, trial_root / "result.json")

            self.assertEqual(output.result.status, AdapterStatus.COMPLETED)
            self.assertEqual(output.result.verifier_outcome, VerifierOutcome.PASSED)
            self.assertEqual(output.result.reward, 1)
            self.assertTrue(output.result.patch_applied)
            controlled_patch = output.patch_path
            self.assertIsNotNone(controlled_patch)
            assert controlled_patch is not None
            self.assertTrue(controlled_patch.is_file())
            self.assertTrue(output.result.job_id.startswith("trial-"))
            self.assertNotIn("secret", output.result.canonical_json())

    def test_runners_reject_dot_components_before_creating_work_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _task()
            manifest = _manifest(task).model_copy(update={"run_id": ".."})
            harbor_request = HarborExecutionRequest(
                repository_root=root,
                artifact=_artifact(root),
                manifest=manifest,
                task=task,
                output_dir=root / "harbor-output",
            )
            harbor_output = HarborSingleTaskRunner().run(harbor_request)
            self.assertEqual(harbor_output.result.status, AdapterStatus.INVALID)
            self.assertFalse((root / "harbor-output" / ".harbor-run").exists())

            patch_path = root / "lion.patch"
            patch_bytes = b"diff --git a/x b/x\n"
            patch_path.write_bytes(patch_bytes)
            harness_output = OfficialSWEbenchHarnessRunner().run(
                HarnessExecutionRequest(
                    instance_id="swebench-task-1",
                    patch_path=patch_path,
                    patch_sha256=hashlib.sha256(patch_bytes).hexdigest(),
                    model_name="test-model",
                    run_id="..",
                    output_dir=root / "harness-output",
                    timeout_seconds=30,
                    image_digest="sha256:" + "b" * 64,
                )
            )
            self.assertEqual(harness_output.result.status, AdapterStatus.INVALID)
            self.assertFalse((root / "harness-output" / ".harness-run").exists())

    def test_harness_writes_prediction_then_blocks_without_linux(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch_path = root / "lion.patch"
            patch_bytes = b"diff --git a/x b/x\r\n"
            patch_path.write_bytes(patch_bytes)
            request = HarnessExecutionRequest(
                instance_id="swebench-task-1",
                patch_path=patch_path,
                patch_sha256=hashlib.sha256(patch_bytes).hexdigest(),
                model_name="test-model",
                run_id="harness-run-1",
                output_dir=root / "output",
                timeout_seconds=30,
                image_digest="sha256:" + "b" * 64,
            )

            with patch(
                "benchmarks.agent_e2e.harness_runner.platform.system",
                return_value="Windows",
            ):
                output = OfficialSWEbenchHarnessRunner().run(request)

            self.assertEqual(output.result.status, AdapterStatus.UNAVAILABLE)
            self.assertEqual(output.result.failure_source, FailureSource.DOCKER)
            prediction_path = output.prediction_path
            self.assertIsNotNone(prediction_path)
            assert prediction_path is not None
            prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
            self.assertEqual(prediction["model_patch"], patch_bytes.decode())
            self.assertEqual(prediction["instance_id"], request.instance_id)
            self.assertFalse((root / "output" / ".harness-run").exists())

    def test_official_harness_report_preserves_resolved_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch_path = root / "lion.patch"
            patch_bytes = b"diff --git a/x b/x\n"
            patch_path.write_bytes(patch_bytes)
            request = HarnessExecutionRequest(
                instance_id="swebench-task-1",
                patch_path=patch_path,
                patch_sha256=hashlib.sha256(patch_bytes).hexdigest(),
                model_name="test-model",
                run_id="harness-run-1",
                output_dir=root / "output",
                timeout_seconds=30,
                image_digest="sha256:" + "b" * 64,
            )
            report_path = root / "report.json"
            report_text = json.dumps(
                {request.instance_id: {"resolved": True}},
                sort_keys=True,
            )
            report_path.write_text(report_text, encoding="utf-8")

            result = _parse_official_report(request, report_path)

            self.assertEqual(result.status, AdapterStatus.COMPLETED)
            self.assertTrue(result.resolved)
            self.assertEqual(result.evaluator_revision, SWEBENCH_EVALUATOR_REVISION)
            self.assertEqual(
                result.output_digest,
                hashlib.sha256(report_text.encode()).hexdigest(),
            )
            self.assertEqual(request.dataset_name, SWEBENCH_DATASET)

    def test_verified_runner_blocks_before_artifact_when_budget_is_not_online(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _task()
            manifest = _manifest(task, budget_usd=0)
            output = run_verified_evaluation(
                VerifiedExecutionRequest(
                    repository_root=root,
                    commit_sha="abcdef0",
                    manifest=manifest,
                    task=task,
                    output_dir=root / "output",
                    python_executable=sys.executable,
                    harness_python=sys.executable,
                )
            )

            self.assertEqual(output.report.task_result.verdict, TaskVerdict.BLOCKED)
            self.assertFalse(output.report.task_result.official)
            self.assertIsNone(output.artifact)
            self.assertFalse((root / "output" / "artifacts").exists())


if __name__ == "__main__":
    unittest.main()
