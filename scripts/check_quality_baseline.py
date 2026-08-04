#!/usr/bin/env python3
"""检查质量工具输出是否超过已提交的机器基线。"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

DEFAULT_BASELINE = Path("docs/quality-baseline-2026-08.json")
HIGH_COMPLEXITY_RANKS = {"D", "E", "F"}


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _read_text(path: Path) -> str:
    content = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def normalize_path(value: str, *, root: Path | None = None) -> str:
    """把工具输出中的绝对/Windows 路径归一成仓库相对 POSIX 路径。"""

    repo_root = (root or Path.cwd()).resolve()
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            pass
    normalized = value.replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def _baseline_section(baseline: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = baseline.get("tools", {}).get(name)
    if not isinstance(section, Mapping):
        raise SystemExit(f"baseline missing tools.{name}")
    return section


def _print_new_fingerprints(fingerprints: Iterable[str]) -> None:
    listed = list(fingerprints)
    for fingerprint in listed[:20]:
        print(f"  {fingerprint}")
    if len(listed) > 20:
        print(f"  ... and {len(listed) - 20} more")


def _check_status(status: int | None, *, allowed: set[int], output_path: Path) -> None:
    if status is None or status in allowed:
        return
    print(_read_text(output_path))
    raise SystemExit(status)


def _check_fingerprints(
    *,
    label: str,
    current: list[str],
    baseline_section: Mapping[str, Any],
    max_key: str = "max_count",
) -> None:
    baseline_max = int(baseline_section[max_key])
    baseline_fingerprints = set(baseline_section.get("fingerprints", []))
    current_set = set(current)
    new_fingerprints = sorted(current_set - baseline_fingerprints)

    print(f"{label}: {len(current)} (baseline {baseline_max})")
    if len(current) > baseline_max:
        print(f"::error::{label} count {len(current)} exceeds baseline {baseline_max}")
        raise SystemExit(1)
    if new_fingerprints:
        print(f"::error::{label} has new fingerprints:")
        _print_new_fingerprints(new_fingerprints)
        raise SystemExit(1)


def ruff_check_fingerprints(
    items: list[Mapping[str, Any]], *, root: Path | None = None
) -> list[str]:
    fingerprints: list[str] = []
    for item in items:
        location = item.get("location", {})
        path = normalize_path(str(item["filename"]), root=root)
        row = int(location.get("row", 0))
        column = int(location.get("column", 0))
        code = str(item.get("code") or "UNKNOWN")
        fingerprints.append(f"{path}:{row}:{column}:{code}")
    return sorted(fingerprints)


FORMAT_LOCATION_RE = re.compile(r"^\s*-->\s+(.+):(\d+):(\d+)\s*$")
FORMAT_SUMMARY_RE = re.compile(r"(?P<count>\d+) files? would be reformatted")


def ruff_format_fingerprints(
    output: str, *, root: Path | None = None
) -> tuple[int, list[str]]:
    fingerprints: set[str] = set()
    for line in output.splitlines():
        match = FORMAT_LOCATION_RE.match(line)
        if match:
            fingerprints.add(normalize_path(match.group(1), root=root))

    summary = FORMAT_SUMMARY_RE.search(output)
    count = int(summary.group("count")) if summary else len(fingerprints)
    if count > 0 and not fingerprints:
        raise SystemExit("unable to parse ruff format file fingerprints")
    return count, sorted(fingerprints)


def mypy_fingerprints(output: str, *, root: Path | None = None) -> list[str]:
    fingerprints: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        path = normalize_path(str(item["file"]), root=root)
        line_no = int(item.get("line") or 0)
        column = int(item.get("column") or 0)
        code = str(item.get("code") or "no-code")
        fingerprints.append(f"{path}:{line_no}:{column}:{code}")
    return sorted(fingerprints)


def radon_high_complexity_fingerprints(
    report: Mapping[str, list[Mapping[str, Any]]], *, root: Path | None = None
) -> list[str]:
    fingerprints: list[str] = []
    for filename, blocks in report.items():
        path = normalize_path(filename, root=root)
        for block in blocks:
            rank = str(block.get("rank", ""))
            if rank not in HIGH_COMPLEXITY_RANKS:
                continue
            class_name = block.get("classname")
            name = str(block.get("name", "<unknown>"))
            symbol = f"{class_name}.{name}" if class_name else name
            line_no = int(block.get("lineno") or 0)
            complexity = int(block.get("complexity") or 0)
            fingerprints.append(f"{path}:{line_no}:{symbol}:{rank}:{complexity}")
    return sorted(fingerprints)


VULTURE_RE = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): (?P<message>.+) "
    r"\((?P<confidence>\d+)% confidence\)$"
)


def vulture_fingerprints(output: str, *, root: Path | None = None) -> list[str]:
    fingerprints: list[str] = []
    for line in output.splitlines():
        match = VULTURE_RE.match(line)
        if not match:
            continue
        path = normalize_path(match.group("path"), root=root)
        fingerprints.append(
            f"{path}:{match.group('line')}:{match.group('message')}:"
            f"{match.group('confidence')}"
        )
    return sorted(fingerprints)


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def changed_lines_from_diff(diff_text: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current_file: str | None = None
    current_line: int | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current_file = None
            current_line = None
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            current_file = None if target == "/dev/null" else normalize_path(target)
            current_line = None
            continue
        match = HUNK_RE.match(line)
        if match:
            current_line = int(match.group("start"))
            continue
        if current_file is None or current_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            changed.setdefault(current_file, set()).add(current_line)
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            current_line += 1

    return changed


def _coverage_files(
    report: Mapping[str, Any], *, root: Path | None = None
) -> dict[str, Mapping[str, Any]]:
    files = report.get("files", {})
    return {normalize_path(path, root=root): data for path, data in files.items()}


def _branch_percent(report: Mapping[str, Any]) -> float:
    totals = report.get("totals", {})
    if "percent_branches_covered" in totals:
        return float(totals["percent_branches_covered"])
    return float(totals.get("percent_covered", 0.0))


def check_changed_line_coverage(
    report: Mapping[str, Any],
    diff_text: str,
    *,
    threshold: float,
    root: Path | None = None,
) -> None:
    files = _coverage_files(report, root=root)
    executable = 0
    covered = 0

    for path, lines in changed_lines_from_diff(diff_text).items():
        if not path.startswith("lion_code/") or not path.endswith(".py"):
            continue
        file_report = files.get(path)
        if not file_report:
            continue
        executed = set(file_report.get("executed_lines", []))
        missing = set(file_report.get("missing_lines", []))
        measured = executed | missing
        for line in lines:
            if line not in measured:
                continue
            executable += 1
            if line in executed:
                covered += 1

    if executable == 0:
        print("changed-lines coverage: skipped (no changed executable lion_code lines)")
        return

    percent = covered / executable * 100
    print(f"changed-lines coverage: {percent:.2f}% ({covered}/{executable})")
    if percent < threshold:
        print(
            f"::error::changed-lines coverage {percent:.2f}% "
            f"is below baseline {threshold:.2f}%"
        )
        raise SystemExit(1)


def check_ruff_check(args: argparse.Namespace) -> None:
    baseline = _read_json(args.baseline)
    _check_status(args.status, allowed={0, 1}, output_path=args.input)
    items = _read_json(args.input)
    fingerprints = ruff_check_fingerprints(items)
    _check_fingerprints(
        label="ruff check",
        current=fingerprints,
        baseline_section=_baseline_section(baseline, "ruff_check"),
    )


def check_ruff_format(args: argparse.Namespace) -> None:
    baseline = _read_json(args.baseline)
    _check_status(args.status, allowed={0, 1}, output_path=args.input)
    _count, fingerprints = ruff_format_fingerprints(_read_text(args.input))
    section = _baseline_section(baseline, "ruff_format")
    _check_fingerprints(
        label="ruff format",
        current=fingerprints,
        baseline_section=section,
    )


def check_mypy(args: argparse.Namespace) -> None:
    baseline = _read_json(args.baseline)
    _check_status(args.status, allowed={0, 1}, output_path=args.input)
    fingerprints = mypy_fingerprints(_read_text(args.input))
    _check_fingerprints(
        label="mypy",
        current=fingerprints,
        baseline_section=_baseline_section(baseline, "mypy"),
    )


def check_radon(args: argparse.Namespace) -> None:
    baseline = _read_json(args.baseline)
    fingerprints = radon_high_complexity_fingerprints(_read_json(args.input))
    _check_fingerprints(
        label="radon D/E/F complexity",
        current=fingerprints,
        baseline_section=_baseline_section(baseline, "radon_complexity"),
        max_key="max_high_rank_count",
    )


def check_vulture(args: argparse.Namespace) -> None:
    baseline = _read_json(args.baseline)
    _check_status(args.status, allowed={0, 3}, output_path=args.input)
    fingerprints = vulture_fingerprints(_read_text(args.input))
    _check_fingerprints(
        label="vulture",
        current=fingerprints,
        baseline_section=_baseline_section(baseline, "vulture"),
    )


def check_coverage(args: argparse.Namespace) -> None:
    baseline = _read_json(args.baseline)
    coverage_baseline = baseline["coverage"]
    report = _read_json(args.input)
    threshold = float(coverage_baseline["branch_percent_min"])
    percent = _branch_percent(report)
    print(f"branch coverage: {percent:.2f}% (baseline {threshold:.2f}%)")
    if percent < threshold:
        print(
            f"::error::branch coverage {percent:.2f}% is below baseline {threshold:.2f}%"
        )
        raise SystemExit(1)

    diff_text = _read_text(args.diff_file) if args.diff_file else ""
    if diff_text:
        check_changed_line_coverage(
            report,
            diff_text,
            threshold=float(coverage_baseline["changed_lines_percent_min"]),
        )


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--status", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    commands = {
        "ruff-check": check_ruff_check,
        "ruff-format": check_ruff_format,
        "mypy": check_mypy,
        "radon-complexity": check_radon,
        "vulture": check_vulture,
    }
    for name, func in commands.items():
        subparser = subparsers.add_parser(name)
        _add_common_args(subparser)
        subparser.set_defaults(func=func)

    coverage = subparsers.add_parser("coverage")
    _add_common_args(coverage)
    coverage.add_argument("--diff-file", type=Path)
    coverage.set_defaults(func=check_coverage)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
