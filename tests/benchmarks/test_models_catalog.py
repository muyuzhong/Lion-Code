"""评测协议、catalog 和 lock 的离线契约测试。"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from benchmarks.agent_e2e.catalog import (
    CatalogValidationError,
    freeze_catalog,
    validate_catalog,
)
from benchmarks.agent_e2e.models import (
    Catalog,
    EvaluationReport,
    ExperimentManifest,
    ExperimentProfile,
    OfficialScore,
    ReportStatus,
    ResultValidity,
    SchemaVersionError,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)


def make_task(*, task_id: str = "task-1", split: TaskSplit = TaskSplit.REGRESSION) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        family="bugfix",
        split=split,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="修复公开问题。",
        public_setup=("python -m pip install -e .",),
        public_validation_commands=("python -m pytest -q",),
        verifier_identity="hidden-v1",
        gold_evidence_hash="a" * 64,
        difficulty=2,
        involved_files=("lion_code/agent.py",),
    )


def make_profile() -> ExperimentProfile:
    return ExperimentProfile(
        profile_id="offline-test",
        model="fake-model",
        provider="fake",
        prompt_version="prompt-v1",
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=0,
        agent_code_sha="abcdef0",
    )


def make_manifest(task: TaskSpec | None = None) -> tuple[Catalog, ExperimentManifest]:
    task = task or make_task()
    catalog = Catalog(catalog_id="local", catalog_version="v1", tasks=(task,))
    lock = freeze_catalog(catalog)
    profile = make_profile()
    return catalog, ExperimentManifest(
        run_id="offline-run",
        agent_code_sha="abcdef0",
        evaluator_code_sha="1234567",
        catalog=lock,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="offline-test",
    )


class TestVersionedModels(unittest.TestCase):
    def test_round_trip_rejects_unknown_fields_and_bad_version(self) -> None:
        catalog, manifest = make_manifest()
        restored = ExperimentManifest.from_json(manifest.canonical_json())

        self.assertEqual(restored, manifest)
        with self.assertRaises(ValidationError):
            Catalog.model_validate({**catalog.model_dump(), "unexpected": True})
        wrong_version = manifest.model_dump(mode="json")
        wrong_version["schema_version"] = "agent-e2e/v0"
        with self.assertRaises(SchemaVersionError):
            ExperimentManifest.from_dict(wrong_version)

    def test_explicit_extensions_preserve_future_fields_without_opening_top_level(self) -> None:
        _catalog, manifest = make_manifest()
        report = EvaluationReport(
            manifest=manifest,
            results=(),
            status=ReportStatus.OFFLINE,
            extensions={"future_gate": {"label": "kept"}},
        )

        restored = EvaluationReport.from_json(report.canonical_json())

        self.assertEqual(restored.extensions["future_gate"]["label"], "kept")
        with self.assertRaises(ValidationError):
            EvaluationReport.model_validate(
                {**report.model_dump(), "future_gate": {"label": "not allowed"}}
            )
        with self.assertRaises(ValidationError):
            EvaluationReport(
                manifest=manifest,
                results=(),
                status=ReportStatus.OFFLINE,
                extensions={"api_key": "not allowed"},
            )

    def test_official_verdict_cannot_be_created_from_offline_result(self) -> None:
        with self.assertRaises(ValidationError):
            TaskResult(
                task_id="task-1",
                attempt=1,
                verdict=TaskVerdict.PASSED,
                validity=ResultValidity.OFFLINE_ONLY,
                official=False,
            )

    def test_official_result_and_score_must_match_verifier_evidence(self) -> None:
        _catalog, manifest = make_manifest()
        verifier = VerifierResult(
            outcome=VerifierOutcome.FAILED,
            command_summary="hidden verifier",
            exit_code=1,
            output_digest="b" * 64,
        )
        with self.assertRaises(ValidationError):
            TaskResult(
                task_id="task-1",
                attempt=1,
                verdict=TaskVerdict.PASSED,
                validity=ResultValidity.VALID,
                official=True,
                patch_sha256="a" * 64,
                verifier=verifier,
            )

        passed_verifier = verifier.model_copy(
            update={"outcome": VerifierOutcome.PASSED, "exit_code": 0}
        )
        passed_result = TaskResult(
            task_id="task-1",
            attempt=1,
            verdict=TaskVerdict.PASSED,
            validity=ResultValidity.VALID,
            official=True,
            patch_sha256="a" * 64,
            verifier=passed_verifier,
        )
        with self.assertRaises(ValidationError):
            EvaluationReport(
                manifest=manifest,
                results=(passed_result,),
                status=ReportStatus.OFFICIAL,
                official_score=OfficialScore(
                    passed_count=0,
                    failed_count=1,
                    valid_denominator=1,
                    success_rate=0,
                ),
            )


class TestCatalogValidation(unittest.TestCase):
    def test_catalog_lock_round_trip_and_selection(self) -> None:
        first = make_task(task_id="task-1")
        second = make_task(task_id="task-2", split=TaskSplit.HOLDOUT)
        catalog = Catalog(catalog_id="local", catalog_version="v1", tasks=(first, second))
        lock = freeze_catalog(catalog, task_ids=("task-2",))

        validation = validate_catalog(catalog, lock=lock)

        self.assertEqual(validation.task_count, 2)
        self.assertEqual(lock.task_ids, ("task-2",))

    def test_duplicate_ids_evidence_and_stale_lock_are_rejected(self) -> None:
        first = make_task(task_id="duplicated")
        duplicate = make_task(task_id="duplicated", split=TaskSplit.HOLDOUT)
        duplicate_catalog = Catalog(
            catalog_id="local",
            catalog_version="v1",
            tasks=(first, duplicate),
        )
        with self.assertRaisesRegex(CatalogValidationError, "duplicate"):
            validate_catalog(duplicate_catalog)

        no_evidence = first.model_copy(update={"gold_evidence_hash": ""})
        invalid_catalog = Catalog(
            catalog_id="local",
            catalog_version="v1",
            tasks=(no_evidence,),
        )
        with self.assertRaisesRegex(CatalogValidationError, "gold evidence"):
            validate_catalog(invalid_catalog)

        catalog = Catalog(catalog_id="local", catalog_version="v1", tasks=(first,))
        lock = freeze_catalog(catalog)
        stale_lock = lock.model_copy(update={"catalog_sha256": "b" * 64})
        with self.assertRaisesRegex(CatalogValidationError, "SHA-256"):
            validate_catalog(catalog, lock=stale_lock)


if __name__ == "__main__":
    unittest.main()
