from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_quality_baseline.py"
)
SPEC = importlib.util.spec_from_file_location("check_quality_baseline", SCRIPT_PATH)
assert SPEC is not None
quality = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(quality)


def test_ruff_format_fingerprints_parse_windows_paths() -> None:
    output = """
unformatted: File would be reformatted
   --> lion_code\\agent.py:1:1

103 files would be reformatted, 99 files already formatted
"""

    count, fingerprints = quality.ruff_format_fingerprints(output)

    assert count == 103
    assert fingerprints == ["lion_code/agent.py"]


def test_read_json_accepts_powershell_utf16_redirect(tmp_path: Path) -> None:
    output = tmp_path / "ruff.json"
    output.write_text("[]", encoding="utf-16")

    assert quality._read_json(output) == []


def test_mypy_json_lines_use_file_line_column_and_code() -> None:
    output = (
        '{"file":"lion_code\\\\ui.py","line":21,"column":4,'
        '"message":"bad","code":"union-attr"}\n'
    )

    assert quality.mypy_fingerprints(output) == ["lion_code/ui.py:21:4:union-attr"]


def test_changed_lines_from_diff_tracks_only_added_lines() -> None:
    diff = """
diff --git a/lion_code/foo.py b/lion_code/foo.py
--- a/lion_code/foo.py
+++ b/lion_code/foo.py
@@ -10,3 +10,4 @@
 keep
-old
+new
+added
 keep
"""

    assert quality.changed_lines_from_diff(diff) == {"lion_code/foo.py": {11, 12}}


def test_changed_line_coverage_fails_below_threshold() -> None:
    report = {
        "files": {
            "lion_code/foo.py": {
                "executed_lines": [10],
                "missing_lines": [11],
            }
        }
    }
    diff = """
diff --git a/lion_code/foo.py b/lion_code/foo.py
--- a/lion_code/foo.py
+++ b/lion_code/foo.py
@@ -10,2 +10,2 @@
+covered
+missing
"""

    with pytest.raises(SystemExit):
        quality.check_changed_line_coverage(report, diff, threshold=80.0)


def test_gate_percent_uses_two_decimal_display_precision() -> None:
    assert quality._gate_percent(58.329) == 58.33
