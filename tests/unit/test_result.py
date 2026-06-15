"""StopReason / RunResult 终止契约的单元测试（ADR-015）。"""
from dataclasses import FrozenInstanceError

import pytest

from runtime.result import RunResult, StopReason


def test_stop_reason_equals_legacy_string():
    # str 枚举：== 旧字符串仍成立，保护既有 13 处 `.reason == "..."` 断言与 CLI 展示。
    assert StopReason.COMPLETED == "completed"
    assert StopReason.PROVIDER_ERROR == "provider_error"
    assert StopReason.USER_ABORT == "user_abort"


def test_stop_reason_str_renders_value():
    # 锁定跨版本显示：str() 必须渲染为值，否则 CLI 会退化为 "StopReason.COMPLETED"。
    assert str(StopReason.COMPLETED) == "completed"


def test_stop_reason_fstring_renders_value():
    assert f"{StopReason.COMPLETED}" == "completed"


def test_run_result_defaults_to_none():
    result = RunResult(StopReason.COMPLETED)
    assert result.final_message_id is None
    assert result.error is None
    assert result.detail is None


def test_run_result_is_frozen():
    result = RunResult(StopReason.COMPLETED)
    with pytest.raises(FrozenInstanceError):
        result.reason = StopReason.FATAL
