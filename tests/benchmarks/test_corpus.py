"""Lion 历史回放任务集的准入与 provenance 测试。"""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from benchmarks.agent_e2e.catalog import (
    CatalogValidationError,
    load_catalog_lock,
    validate_catalog,
)
from benchmarks.agent_e2e.corpus import (
    CorpusAdmissionError,
    bundled_catalog,
    bundled_private_evidence,
    run_historical_preflight,
    validate_bundled_corpus,
    validate_corpus,
)
from benchmarks.agent_e2e.models import Catalog, TaskSplit


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PUBLIC_CATALOG_PATH = (
    _REPOSITORY_ROOT
    / "benchmarks"
    / "agent_e2e"
    / "corpus_assets"
    / "public_catalog.v1.json"
)
_PUBLIC_CATALOG_SHA_PATH = _PUBLIC_CATALOG_PATH.with_suffix(".sha256")
_PUBLIC_CATALOG_LOCK_PATH = _PUBLIC_CATALOG_PATH.with_suffix(".lock.json")


class TestHistoricalReplayCorpus(unittest.TestCase):
    def test_bundled_catalog_has_required_mix_and_private_boundary(self) -> None:
        catalog = validate_bundled_corpus()
        evidence = bundled_private_evidence()

        self.assertEqual(len(catalog.tasks), 30)
        self.assertEqual(
            sum(task.family == "cross_file_refactor" for task in catalog.tasks),
            10,
        )
        self.assertEqual(sum(task.family == "bugfix" for task in catalog.tasks), 10)
        self.assertEqual(sum(task.family == "feature" for task in catalog.tasks), 10)
        self.assertEqual(
            sum(task.split is TaskSplit.REGRESSION for task in catalog.tasks),
            18,
        )
        self.assertEqual(sum(task.split is TaskSplit.HOLDOUT for task in catalog.tasks), 12)
        public_payload = catalog.canonical_json()
        self.assertNotIn('"gold_revision"', public_payload)
        for task in catalog.tasks:
            self.assertNotEqual(
                task.base_revision,
                evidence[task.task_id].gold_revision,
            )

    def test_committed_public_catalog_asset_matches_the_versioned_cards(self) -> None:
        catalog = bundled_catalog()
        committed = Catalog.from_json(_PUBLIC_CATALOG_PATH.read_text(encoding="utf-8"))
        committed_hash = _PUBLIC_CATALOG_SHA_PATH.read_text(encoding="utf-8").strip()

        self.assertEqual(committed, catalog)
        self.assertEqual(committed_hash, catalog.fingerprint())
        self.assertEqual(
            validate_catalog(
                committed,
                lock=load_catalog_lock(_PUBLIC_CATALOG_LOCK_PATH),
            ).catalog_sha256,
            catalog.fingerprint(),
        )

    def test_missing_or_unstable_evidence_is_rejected(self) -> None:
        catalog = bundled_catalog()
        evidence = bundled_private_evidence()
        missing = dict(evidence)
        missing.pop("lion-bugfix-01")
        with self.assertRaisesRegex(CorpusAdmissionError, "IDs"):
            validate_corpus(catalog, missing)

        unstable = dict(evidence)
        task_id = "lion-feature-01"
        unstable[task_id] = replace(unstable[task_id], stability_repeats=2)
        with self.assertRaisesRegex(CorpusAdmissionError, "three-run"):
            validate_corpus(catalog, unstable)

    def test_duplicate_ids_feedback_and_cross_split_commit_are_rejected(self) -> None:
        catalog = bundled_catalog()
        evidence = bundled_private_evidence()
        duplicate_catalog = Catalog(
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.catalog_version,
            tasks=(catalog.tasks[0], *catalog.tasks),
        )
        with self.assertRaises(CatalogValidationError):
            validate_corpus(duplicate_catalog, evidence)

        holdout_task = next(
            task for task in catalog.tasks if task.split is TaskSplit.HOLDOUT
        )
        with self.assertRaisesRegex(CorpusAdmissionError, "Feedback-derived"):
            validate_corpus(
                catalog,
                evidence,
                feedback_task_ids=(holdout_task.task_id,),
            )

        regression_task = next(
            task for task in catalog.tasks if task.split is TaskSplit.REGRESSION
        )
        contaminated = dict(evidence)
        contaminated[holdout_task.task_id] = replace(
            contaminated[holdout_task.task_id],
            gold_revision=evidence[regression_task.task_id].gold_revision,
        )
        with self.assertRaisesRegex(CorpusAdmissionError, "share historical commits"):
            validate_corpus(catalog, contaminated)

    def test_every_task_has_three_stable_git_provenance_runs(self) -> None:
        catalog = bundled_catalog()
        evidence = bundled_private_evidence()

        results = [
            run_historical_preflight(
                task,
                evidence[task.task_id],
                repository_root=_REPOSITORY_ROOT,
            )
            for task in catalog.tasks
        ]

        self.assertEqual(len(results), 30)
        self.assertTrue(all(result.base_verdict == "fail" for result in results))
        self.assertTrue(all(result.gold_verdict == "pass" for result in results))
        self.assertTrue(all(result.stable for result in results))


if __name__ == "__main__":
    unittest.main()
