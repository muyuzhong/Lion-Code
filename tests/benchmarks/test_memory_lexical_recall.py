from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from benchmarks.memory_lexical_recall.benchmark import (
    read_fixture,
    render_report,
    run_benchmark,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "memory_lexical_recall" / "benchmark.py"
REPORT = ROOT / "benchmarks" / "memory_lexical_recall" / "report.v1.md"


def test_fixture_covers_required_recall_categories():
    fixture = read_fixture()

    categories = {query["category"] for query in fixture["queries"]}

    assert {
        "zh_two_char",
        "zh_natural_language",
        "english_error",
        "code_symbol",
        "command",
        "path",
        "negative",
        "project_isolation",
        "project_isolation_negative",
    } <= categories


def test_all_strategies_are_deterministic_and_project_isolated(tmp_path: Path):
    fixture = read_fixture()

    first = run_benchmark(fixture, database_directory=tmp_path / "first")
    (tmp_path / "second").mkdir()
    second = run_benchmark(fixture, database_directory=tmp_path / "second")

    assert first == second
    assert [result.name for result in first.strategies] == [
        "literal",
        "unicode61",
        "trigram",
    ]
    assert all(result.project_isolation_rate == 1.0 for result in first.strategies)
    assert all(
        not result.results["project-isolation-negative"] for result in first.strategies
    )


def test_trigram_reports_two_character_chinese_limitation(tmp_path: Path):
    fixture = read_fixture()
    result = run_benchmark(fixture, database_directory=tmp_path)
    by_name = {strategy.name: strategy for strategy in result.strategies}

    assert by_name["literal"].results["zh-two-char-wait"] == ("ci-merge-gate",)
    assert by_name["trigram"].results["zh-two-char-wait"] == ()

    report = render_report(result)
    assert "少于三个 Unicode 字符" in report
    assert "不得把 trigram 概括为“支持中文”" in report


def test_fts_query_is_escaped_as_data(tmp_path: Path):
    fixture = read_fixture()
    query = next(item for item in fixture["queries"] if item["id"] == "negative-symbol")
    query["query"] = '" OR scope:*; DROP TABLE memory_fts; --'

    result = run_benchmark(fixture, database_directory=tmp_path)

    assert all(not strategy.results[query["id"]] for strategy in result.strategies)


def test_go_only_authorizes_phase_two_replanning(tmp_path: Path):
    result = run_benchmark(read_fixture(), database_directory=tmp_path)
    by_name = {strategy.name: strategy for strategy in result.strategies}

    assert result.go
    assert by_name["literal"].recall_at_5 == 1.0
    assert by_name["unicode61"].recall_at_5 == 0.8
    assert by_name["trigram"].recall_at_5 == 0.9
    assert all(
        strategy.negative_false_recall_rate == 0.0 for strategy in result.strategies
    )
    report = render_report(result)
    assert "**GO**" in report
    assert "值得重新规划二期" in report
    assert "不授权实现、接入或发布二期自动召回" in report
    assert REPORT.read_text(encoding="utf-8") == report


def test_fixed_command_uses_only_temporary_database(tmp_path: Path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={"HOME": str(fake_home), "USERPROFILE": str(fake_home)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Memory lexical 召回离线原型报告" in result.stdout
    assert REPORT.read_text(encoding="utf-8") == result.stdout
    assert not (fake_home / ".lion-code").exists()
