"""SWE-bench-Live 外部锚点的冻结、预检、归一化与校准契约。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from benchmarks.agent_e2e.cli import main as evaluation_cli_main
from benchmarks.agent_e2e.external_anchor import (
    AnchorRunStatus,
    CalibrationPoint,
    CalibrationProfileKind,
    ExternalAnchorDriftError,
    ExternalAnchorError,
    ExternalAnchorManifest,
    OfficialEvaluationRecord,
    OfficialRecordStatus,
    UnavailableOfficialSWEbenchLiveRunner,
    calibrate_external_anchor,
    require_comparable_external_reports,
    run_external_anchor_evaluation,
    select_external_anchor_instances,
    validate_bundled_external_anchor_manifest,
    validate_manifest_against_snapshot,
    validate_materialized_dataset_snapshot,
    write_external_anchor_report,
    write_materialized_dataset_snapshot,
)
from benchmarks.agent_e2e.models import TaskVerdict


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class FakeOfficialRunner:
    """测试用 runner，显式模拟官方摘要，不允许它绕过生产 unavailable 路径。"""

    gold_outcomes: dict[str, tuple[bool, bool, bool]]
    model_outcomes: dict[str, bool]
    image_digests: bool = True
    _gold_attempt: int = 0
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> None:
        return None

    def evaluate(
        self,
        *,
        manifest,
        patch_source: str | Path,
        instance_ids: Sequence[str],
        output_dir: Path,
        workers: int,
    ) -> tuple[OfficialEvaluationRecord, ...]:
        source = str(patch_source)
        self.calls.append((source, tuple(instance_ids)))
        if source == "gold":
            attempt = self._gold_attempt
            self._gold_attempt += 1
            outcomes = {
                instance_id: self.gold_outcomes[instance_id][attempt]
                for instance_id in instance_ids
            }
        else:
            outcomes = {instance_id: self.model_outcomes[instance_id] for instance_id in instance_ids}
        records = []
        for instance_id in instance_ids:
            instance = manifest.instance_by_id[instance_id]
            image_digest = f"sha256:{_digest(instance_id)}" if self.image_digests else None
            records.append(
                OfficialEvaluationRecord(
                    instance_id=instance_id,
                    status=OfficialRecordStatus.COMPLETED,
                    resolved=outcomes[instance_id],
                    output_digest=_digest(f"{source}:{instance_id}:{outcomes[instance_id]}"),
                    command_digest=_digest(f"{source}:{attempt if source == 'gold' else 0}"),
                    image_reference=instance.image_reference,
                    image_digest=image_digest,
                )
            )
        return tuple(records)


@pytest.fixture
def manifest():
    return validate_bundled_external_anchor_manifest()


def _write_predictions(path: Path, manifest) -> Path:
    path.write_text(
        json.dumps(
            {
                instance_id: {"model_patch": f"diff --git a/{instance_id} b/{instance_id}"}
                for instance_id in manifest.instance_ids
            }
        ),
        encoding="utf-8",
    )
    return path


def _runner(manifest, *, unstable_id: str | None = None, image_digests: bool = True) -> FakeOfficialRunner:
    gold = {instance_id: (True, True, True) for instance_id in manifest.instance_ids}
    if unstable_id is not None:
        gold[unstable_id] = (True, False, True)
    model = {
        instance_id: index % 2 == 0
        for index, instance_id in enumerate(manifest.instance_ids)
    }
    return FakeOfficialRunner(gold, model, image_digests=image_digests)


def _snapshot_rows(manifest) -> list[dict[str, object]]:
    return [
        {
            "instance_id": item.instance_id,
            "repo": item.repository,
            "base_commit": item.base_commit,
            "created_at": item.created_at,
            "difficulty": {
                "files": item.difficulty_files,
                "hunks": item.difficulty_hunks,
                "lines": item.difficulty_lines,
            },
        }
        for item in manifest.instances
    ]


def _rows_digest(rows: list[dict[str, object]]) -> str:
    canonical = json.dumps(
        sorted(rows, key=lambda row: str(row["instance_id"])),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(canonical)


def _manifest_with_row_count(
    manifest,
    count: int,
    rows: list[dict[str, object]],
    *,
    canonical_rows: list[dict[str, object]] | None = None,
):
    payload = manifest.model_dump(mode="json")
    payload["dataset_rows"] = count
    payload["selected_rows_sha256"] = _rows_digest(canonical_rows or rows)
    return ExternalAnchorManifest.model_validate(payload)


def test_bundled_manifest_is_frozen_and_deterministic(manifest) -> None:
    assert manifest.dataset_split == "verified"
    assert len(manifest.instances) == 20
    assert {item.stratum for item in manifest.instances} == {
        "files_1",
        "files_2",
        "files_3_4",
        "files_5_plus",
    }
    assert [item.stratum for item in manifest.instances].count("files_1") == 5
    assert len({item.repository.casefold() for item in manifest.instances}) == 20

    selected = select_external_anchor_instances(_snapshot_rows(manifest), seed=manifest.selection_seed)
    assert selected == manifest.instances


def test_external_anchor_cli_validates_without_network_or_docker(capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluation_cli_main(["external-anchor-validate", "--show-instance-ids"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "valid"
    assert payload["instance_count"] == 20
    assert len(payload["instance_ids"]) == 20


def test_snapshot_validation_detects_selected_metadata_drift(manifest) -> None:
    rows = _snapshot_rows(manifest)
    small_manifest = _manifest_with_row_count(manifest, 20, rows)
    validate_manifest_against_snapshot(small_manifest, rows)

    rows[0]["base_commit"] = "0" * 40
    with pytest.raises(ExternalAnchorDriftError, match="metadata drifted"):
        validate_manifest_against_snapshot(small_manifest, rows)


def test_snapshot_validation_tolerates_identical_source_duplicates(manifest) -> None:
    rows = _snapshot_rows(manifest)
    duplicate_rows = [*rows, dict(rows[0])]
    duplicate_manifest = _manifest_with_row_count(
        manifest,
        21,
        duplicate_rows,
        canonical_rows=rows,
    )
    validate_manifest_against_snapshot(duplicate_manifest, duplicate_rows)


def test_materialized_snapshot_requires_full_row_hash(manifest, tmp_path: Path) -> None:
    rows = _snapshot_rows(manifest)
    small_manifest = _manifest_with_row_count(manifest, 20, rows)
    path = write_materialized_dataset_snapshot(
        small_manifest,
        rows,
        output_path=tmp_path / "swe-bench-live.jsonl",
    )
    validate_materialized_dataset_snapshot(small_manifest, path)

    changed = path.read_text(encoding="utf-8").replace("python-control", "python-control-x", 1)
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(ExternalAnchorDriftError, match="snapshot"):
        validate_materialized_dataset_snapshot(small_manifest, path)


def test_unavailable_runner_is_blocked_without_external_score(manifest, tmp_path: Path) -> None:
    report = run_external_anchor_evaluation(
        manifest,
        runner=UnavailableOfficialSWEbenchLiveRunner("Docker daemon is unavailable"),
        prediction_path=_write_predictions(tmp_path / "predictions.json", manifest),
        output_root=tmp_path / "output",
    )

    assert report.status is AnchorRunStatus.BLOCKED
    assert report.success_rate is None
    assert report.valid_denominator == 0
    assert {result.verdict for result in report.task_results} == {TaskVerdict.BLOCKED}


def test_gold_preflight_excludes_unstable_case_and_uses_actual_denominator(manifest, tmp_path: Path) -> None:
    unstable_id = manifest.instance_ids[0]
    runner = _runner(manifest, unstable_id=unstable_id)
    report = run_external_anchor_evaluation(
        manifest,
        runner=runner,
        prediction_path=_write_predictions(tmp_path / "predictions.json", manifest),
        output_root=tmp_path / "output",
        workers=2,
    )

    assert report.status is AnchorRunStatus.COMPLETED
    assert report.valid_denominator == 19
    assert unstable_id not in report.gold_preflight.stable_instance_ids
    assert report.success_rate == pytest.approx(report.passed / 19)
    unstable_result = next(result for result in report.task_results if result.task_id == unstable_id)
    assert unstable_result.verdict is TaskVerdict.INVALID
    official = [result for result in report.task_results if result.official]
    assert len(official) == 19
    assert all(result.verifier is not None for result in official)
    assert len(runner.calls) == 4


def test_missing_image_digest_blocks_official_score(manifest, tmp_path: Path) -> None:
    report = run_external_anchor_evaluation(
        manifest,
        runner=_runner(manifest, image_digests=False),
        prediction_path=_write_predictions(tmp_path / "predictions.json", manifest),
        output_root=tmp_path / "output",
    )

    assert report.status is AnchorRunStatus.INVALID
    assert report.success_rate is None
    assert "image digest" in (report.reason or "")


def test_prediction_ids_must_exactly_match_frozen_manifest(manifest, tmp_path: Path) -> None:
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({manifest.instance_ids[0]: {"model_patch": "diff"}}), encoding="utf-8")

    report = run_external_anchor_evaluation(
        manifest,
        runner=_runner(manifest),
        prediction_path=path,
        output_root=tmp_path / "output",
    )
    assert report.status is AnchorRunStatus.INVALID
    assert report.success_rate is None
    assert "exactly match" in (report.reason or "")


def test_report_writer_keeps_only_controlled_artifacts(manifest, tmp_path: Path) -> None:
    report = run_external_anchor_evaluation(
        manifest,
        runner=_runner(manifest),
        prediction_path=_write_predictions(tmp_path / "predictions.json", manifest),
        output_root=tmp_path / "output",
    )
    json_path, markdown_path = write_external_anchor_report(report, output_dir=tmp_path / "report")

    contents = json_path.read_text(encoding="utf-8")
    assert "model_patch" not in contents
    assert "SWE-bench-Live" in markdown_path.read_text(encoding="utf-8")


def test_environment_drift_rejects_comparison(manifest, tmp_path: Path) -> None:
    report = run_external_anchor_evaluation(
        manifest,
        runner=_runner(manifest),
        prediction_path=_write_predictions(tmp_path / "predictions.json", manifest),
        output_root=tmp_path / "output",
    )
    assert report.environment is not None
    drifted_environment = report.environment.model_copy(
        update={"evaluator_revision": "f" * 40}
    )
    drifted_report = report.model_copy(update={"environment": drifted_environment})

    with pytest.raises(ExternalAnchorDriftError, match="drift"):
        require_comparable_external_reports(report, drifted_report)


def test_calibration_requires_profile_mix_and_reports_rank_validity(manifest, tmp_path: Path) -> None:
    external_report = run_external_anchor_evaluation(
        manifest,
        runner=_runner(manifest),
        prediction_path=_write_predictions(tmp_path / "predictions.json", manifest),
        output_root=tmp_path / "output",
    )
    assert external_report.environment is not None
    points = []
    profile_kinds = (
        CalibrationProfileKind.BASELINE,
        CalibrationProfileKind.CANDIDATE,
        CalibrationProfileKind.CANDIDATE,
        CalibrationProfileKind.CANDIDATE,
        CalibrationProfileKind.DEGRADED,
    )
    for index, kind in enumerate(profile_kinds):
        points.append(
            CalibrationPoint(
                profile_id=f"profile-{index}",
                profile_fingerprint=f"{index + 1:064x}",
                profile_kind=kind,
                self_holdout_passed=index + 1,
                self_holdout_denominator=10,
                external_report_fingerprint=_digest(f"report-{index}"),
                external_passed=index + 1,
                external_denominator=10,
                external_success_rate=(index + 1) / 10,
                environment=external_report.environment,
            )
        )

    calibration = calibrate_external_anchor(points)
    assert calibration.spearman_rho == pytest.approx(1.0)
    assert calibration.direction_agreement == pytest.approx(1.0)
    assert calibration.accepted is True

    no_degraded = [
        point for point in points if point.profile_kind is not CalibrationProfileKind.DEGRADED
    ]
    no_degraded.append(
        points[1].model_copy(
            update={"profile_id": "profile-extra", "profile_fingerprint": "f" * 64}
        )
    )
    with pytest.raises(ExternalAnchorError, match="degraded"):
        calibrate_external_anchor(no_degraded)
