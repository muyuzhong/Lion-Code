from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "context_management" / "formal_benchmark.py"


def load_formal_benchmark():
    spec = importlib.util.spec_from_file_location("lion_formal_benchmark", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_formal_dataset_is_balanced_and_executable():
    benchmark = load_formal_benchmark()
    dataset = benchmark.read_dataset()

    validation = benchmark.validate_dataset(dataset)

    assert validation["passed"], validation["errors"]
    assert validation["task_count"] == 9
    assert validation["matrix_cells"] == 9


def test_formal_order_contains_54_balanced_sessions():
    benchmark = load_formal_benchmark()
    dataset = benchmark.read_dataset()

    order = benchmark.build_run_order(
        dataset["tasks"], dataset["policies"], dataset["repeat_count"], 20260723
    )

    assert len(order) == 54
    keys = {(item["task_id"], item["policy"], item["repeat"]) for item in order}
    assert len(keys) == 54
    assert {item["repeat"] for item in order} == {1, 2}


def test_report_separates_completed_and_interrupted_spend():
    benchmark = load_formal_benchmark()
    payload = {
        "metadata": {
            "generated_at": "2026-07-23T00:00:00+00:00",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "selected_task_count": 1,
            "planned_session_count": 1,
            "completed_session_count": 1,
            "repeat_count": 1,
            "effective_window_tokens": 180_000,
            "benchmark_spend_cny": 1.25,
            "budget_limit_cny": 2.0,
        },
        "aggregate": {
            "managed": {
                "success_count": 1,
                "session_count": 1,
                "all_usage": {"prompt_tokens": 100},
                "cache_hit_rate": 0.5,
                "summary_call_count": 0,
                "peak_prompt_tokens": 100,
                "total_cost_cny": 1.0,
            }
        },
    }

    report = benchmark.render_report(payload)

    assert "完整会话费用：1.0000 元" in report
    assert "中止调用与断点重放费用：0.2500 元" in report


def test_report_formats_bootstrap_intervals_with_units():
    benchmark = load_formal_benchmark()

    assert benchmark.pct_ci([0.0914, 0.1441]) == "[9.1%, 14.4%]"
    assert (
        benchmark.pct_ci([-0.0138, 0.0826], percentage_points=True)
        == "[-1.4, +8.3] 个百分点"
    )
