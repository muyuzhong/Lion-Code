"""比较 Memory literal、FTS5 unicode61 与 trigram 的离线召回水位。

固定复现命令：

``python benchmarks/memory_lexical_recall/benchmark.py``

脚本只读取人工夹具，FTS 数据库创建在临时目录；不会发现、打开或修改用户的
``~/.lion-code/memory.sqlite3``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURE_PATH = Path(__file__).with_name("fixtures.v1.json")
SCHEMA_VERSION = "memory-lexical-recall/v1"
TOP_K = 5
RECALL_WATERLINE = 0.80
PRECISION_WATERLINE = 0.60
NEGATIVE_FALSE_RECALL_CEILING = 0.10
PROJECT_ISOLATION_WATERLINE = 1.0
FTS_STRATEGIES = ("unicode61", "trigram")


@dataclass(frozen=True, slots=True)
class StrategyResult:
    name: str
    recall_at_5: float
    precision_at_5: float
    negative_false_recall_rate: float
    project_isolation_rate: float
    passed_waterline: bool
    results: dict[str, tuple[str, ...]]
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    fixture_sha256: str
    strategies: tuple[StrategyResult, ...]
    go: bool


def read_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_fixture(payload)
    return payload


def _validate_fixture(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"夹具 schema 必须为 {SCHEMA_VERSION}")

    entries = payload.get("entries")
    queries = payload.get("queries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("夹具必须包含非空 entries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("夹具必须包含非空 queries")

    entry_ids = [entry.get("id") for entry in entries]
    if len(entry_ids) != len(set(entry_ids)) or not all(entry_ids):
        raise ValueError("entry id 必须非空且唯一")

    query_ids = [query.get("id") for query in queries]
    if len(query_ids) != len(set(query_ids)) or not all(query_ids):
        raise ValueError("query id 必须非空且唯一")

    known_ids = set(entry_ids)
    for entry in entries:
        scope = entry.get("scope")
        project_key = entry.get("project_key")
        if scope == "long_term" and project_key is not None:
            raise ValueError(f"long_term 条目不得带 project_key: {entry['id']}")
        if scope == "project" and not project_key:
            raise ValueError(f"project 条目必须带 project_key: {entry['id']}")
        if scope not in {"long_term", "project"}:
            raise ValueError(f"未知 scope: {entry['id']}")

    for query in queries:
        expected = query.get("expected_ids")
        if not query.get("query") or not query.get("project_key"):
            raise ValueError(f"query 与 project_key 必须非空: {query['id']}")
        if not isinstance(expected, list) or not set(expected) <= known_ids:
            raise ValueError(f"query expected_ids 无效: {query['id']}")

    categories = {query["category"] for query in queries}
    required = {
        "zh_two_char",
        "zh_natural_language",
        "english_error",
        "code_symbol",
        "command",
        "path",
        "negative",
        "project_isolation",
        "project_isolation_negative",
    }
    if missing := required - categories:
        raise ValueError(f"夹具缺少类别: {sorted(missing)}")


def _eligible(entry: dict[str, Any], project_key: str) -> bool:
    return entry["scope"] == "long_term" or entry["project_key"] == project_key


def _literal_results(
    entries: list[dict[str, Any]], query: dict[str, Any]
) -> tuple[str, ...]:
    needle = query["query"].casefold()
    matches: list[str] = []
    for entry in entries:
        if not _eligible(entry, query["project_key"]):
            continue
        fields = (
            entry["stable_key"],
            entry["content"],
            entry["trigger"],
            *entry["paths"],
        )
        if any(needle in field.casefold() for field in fields):
            matches.append(entry["id"])
    return tuple(sorted(matches)[:TOP_K])


def _fts_phrase(query: str) -> str:
    return f'"{query.replace(chr(34), chr(34) * 2)}"'


def _build_fts_database(
    path: Path, entries: list[dict[str, Any]], tokenizer: str
) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5("
            "entry_id UNINDEXED, scope UNINDEXED, project_key UNINDEXED, "
            "stable_key, content, trigger, paths, "
            f"tokenize='{tokenizer}')"
        )
        connection.executemany(
            "INSERT INTO memory_fts("
            "entry_id, scope, project_key, stable_key, content, trigger, paths"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    entry["id"],
                    entry["scope"],
                    entry["project_key"] or "",
                    entry["stable_key"],
                    entry["content"],
                    entry["trigger"],
                    " ".join(entry["paths"]),
                )
                for entry in entries
            ),
        )
        connection.commit()
    except Exception:
        connection.close()
        raise
    return connection


def _fts_results(
    connection: sqlite3.Connection, query: dict[str, Any]
) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT entry_id FROM memory_fts "
        "WHERE memory_fts MATCH ? "
        "AND (scope = 'long_term' OR project_key = ?) "
        "ORDER BY bm25(memory_fts), entry_id LIMIT ?",
        (_fts_phrase(query["query"]), query["project_key"], TOP_K),
    ).fetchall()
    return tuple(row[0] for row in rows)


def _measure(
    name: str,
    entries: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    results: dict[str, tuple[str, ...]],
) -> StrategyResult:
    negative = [query for query in queries if not query["expected_ids"]]
    recalls: list[float] = []
    precisions: list[float] = []
    failures: list[str] = []

    entry_by_id = {entry["id"]: entry for entry in entries}
    returned_total = 0
    isolated_total = 0
    for query in queries:
        returned = results[query["id"]]
        expected = set(query["expected_ids"])
        hits = expected.intersection(returned)
        if expected:
            recalls.append(len(hits) / len(expected))
            precisions.append(len(hits) / len(returned) if returned else 0.0)
            if hits != expected or set(returned) != expected:
                failures.append(
                    f"{query['id']}: expected={sorted(expected)}, returned={list(returned)}"
                )
        elif returned:
            failures.append(f"{query['id']}: expected=[], returned={list(returned)}")

        returned_total += len(returned)
        isolated_total += sum(
            _eligible(entry_by_id[entry_id], query["project_key"])
            for entry_id in returned
        )

    recall_at_5 = sum(recalls) / len(recalls)
    precision_at_5 = sum(precisions) / len(precisions)
    negative_false_recall_rate = sum(
        bool(results[query["id"]]) for query in negative
    ) / len(negative)
    project_isolation_rate = isolated_total / returned_total if returned_total else 1.0
    passed = (
        recall_at_5 >= RECALL_WATERLINE
        and precision_at_5 >= PRECISION_WATERLINE
        and negative_false_recall_rate <= NEGATIVE_FALSE_RECALL_CEILING
        and project_isolation_rate == PROJECT_ISOLATION_WATERLINE
    )
    return StrategyResult(
        name=name,
        recall_at_5=recall_at_5,
        precision_at_5=precision_at_5,
        negative_false_recall_rate=negative_false_recall_rate,
        project_isolation_rate=project_isolation_rate,
        passed_waterline=passed,
        results=results,
        failures=tuple(failures),
    )


def run_benchmark(
    fixture: dict[str, Any], *, database_directory: Path
) -> BenchmarkResult:
    database_directory.mkdir(parents=True, exist_ok=True)
    entries = fixture["entries"]
    queries = fixture["queries"]
    literal_results = {
        query["id"]: _literal_results(entries, query) for query in queries
    }
    measured = [_measure("literal", entries, queries, literal_results)]

    for tokenizer in FTS_STRATEGIES:
        connection = _build_fts_database(
            database_directory / f"{tokenizer}.sqlite3", entries, tokenizer
        )
        try:
            strategy_results = {
                query["id"]: _fts_results(connection, query) for query in queries
            }
        finally:
            connection.close()
        measured.append(_measure(tokenizer, entries, queries, strategy_results))

    fixture_bytes = json.dumps(
        fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    go = any(
        result.passed_waterline for result in measured if result.name in FTS_STRATEGIES
    )
    return BenchmarkResult(
        fixture_sha256=hashlib.sha256(fixture_bytes).hexdigest(),
        strategies=tuple(measured),
        go=go,
    )


def render_report(result: BenchmarkResult) -> str:
    decision = "GO" if result.go else "NO-GO"
    lines = [
        "# Memory lexical 召回离线原型报告",
        "",
        f"夹具 SHA-256：`{result.fixture_sha256}`",
        "",
        "复现命令：`python benchmarks/memory_lexical_recall/benchmark.py`",
        "",
        "## 口径",
        "",
        f"- top-k：{TOP_K}",
        "- recall@5：正样本逐 query 召回率的宏平均。",
        "- precision@5：正样本实际返回的前五条中相关项比例的宏平均；空结果记 0。",
        "- 负样本误召回率：返回任意结果的负样本 query 比例。",
        "- 项目隔离率：返回结果中属于 long-term 或当前 project 的比例。",
        "- literal 是一期显式召回基线；只有 FTS5 策略参与二期 go/no-go。",
        "",
        "## 水位",
        "",
        "| recall@5 | precision@5 | 负样本误召回率 | 项目隔离率 |",
        "| ---: | ---: | ---: | ---: |",
        f"| ≥ {RECALL_WATERLINE:.2f} | ≥ {PRECISION_WATERLINE:.2f} | ≤ {NEGATIVE_FALSE_RECALL_CEILING:.2f} | = {PROJECT_ISOLATION_WATERLINE:.2f} |",
        "",
        "## 结果",
        "",
        "| 策略 | recall@5 | precision@5 | 负样本误召回率 | 项目隔离率 | 过线 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for strategy in result.strategies:
        lines.append(
            f"| {strategy.name} | {strategy.recall_at_5:.2f} | "
            f"{strategy.precision_at_5:.2f} | "
            f"{strategy.negative_false_recall_rate:.2f} | "
            f"{strategy.project_isolation_rate:.2f} | "
            f"{'是' if strategy.passed_waterline else '否'} |"
        )

    lines.extend(["", "## 失败样例", ""])
    for strategy in result.strategies:
        lines.append(f"### {strategy.name}")
        lines.append("")
        if strategy.failures:
            lines.extend(f"- `{failure}`" for failure in strategy.failures)
        else:
            lines.append("- 无。")
        lines.append("")

    trigram = next(item for item in result.strategies if item.name == "trigram")
    two_char = trigram.results["zh-two-char-wait"]
    lines.extend(
        [
            "## 两字中文限制",
            "",
            "固定 query `等待` 在包含该短语的中文内容中：",
            "",
            f"- trigram 返回：`{list(two_char)}`；",
            "- 这是 FTS5 trigram 无法为少于三个 Unicode 字符形成三元片段的已知限制；",
            "- 报告不得把 trigram 概括为“支持中文”，二期重新规划必须单独处理短 query。",
            "",
            "## Go / No-Go",
            "",
            f"**{decision}**："
            + (
                "至少一个 FTS5 策略达到实验水位，值得重新规划二期 relevant 自动召回。"
                if result.go
                else "没有 FTS5 策略达到实验水位，不值得进入二期规划。"
            ),
            "",
            "本结论只决定是否值得重新规划与评审二期；不选择生产 tokenizer，"
            "不授权实现、接入或发布二期自动召回。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    args = parser.parse_args(argv)

    fixture = read_fixture(args.fixture)
    with tempfile.TemporaryDirectory(prefix="lion-memory-lexical-") as temporary:
        result = run_benchmark(fixture, database_directory=Path(temporary))
    report = render_report(result)
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
