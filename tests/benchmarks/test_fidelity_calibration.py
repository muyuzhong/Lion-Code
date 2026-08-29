"""过程判定校准测试:已知违规检出、正常不误杀、旧 trace 降级。"""

from __future__ import annotations

from pathlib import Path

from benchmarks.agent_e2e.calibration import run_calibration

FIXTURES_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "agent_e2e"
    / "calibration"
)


class TestCalibrationFixtures:
    def test_all_fixtures_pass(self) -> None:
        summary = run_calibration(FIXTURES_ROOT)
        assert summary.outcomes, "calibration fixtures must exist"
        assert summary.passed_count == len(summary.outcomes), (
            summary.render_markdown()
        )

    def test_violation_recall_covers_all_six_types(self) -> None:
        summary = run_calibration(FIXTURES_ROOT)
        violation_fixtures = [
            outcome for outcome in summary.outcomes if outcome.kind == "violations"
        ]
        assert len(violation_fixtures) >= 6, (
            "six violation types need at least one fixture each"
        )

    def test_clean_never_vetoes(self) -> None:
        summary = run_calibration(FIXTURES_ROOT)
        clean_fixtures = [
            outcome for outcome in summary.outcomes if outcome.kind == "clean"
        ]
        assert clean_fixtures, "clean fixtures must exist"
        for outcome in clean_fixtures:
            assert outcome.verification.status.value == "valid", outcome.detail

    def test_legacy_degrades_to_unavailable(self) -> None:
        summary = run_calibration(FIXTURES_ROOT)
        legacy_fixtures = [
            outcome for outcome in summary.outcomes if outcome.kind == "legacy"
        ]
        assert legacy_fixtures, "legacy fixtures must exist"
        assert summary.legacy_unavailable_ratio == 1.0

    def test_summary_markdown_renders(self) -> None:
        summary = run_calibration(FIXTURES_ROOT)
        text = summary.render_markdown()
        assert "# ProcessVerifier 校准小结" in text
        assert "| fixture |" in text