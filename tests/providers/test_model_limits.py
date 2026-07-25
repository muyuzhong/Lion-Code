"""``RuntimeModelLimits`` 校验与派生属性、``ModelLimitsProvider`` 协议测试。"""

from __future__ import annotations

import unittest

from lion_code.providers.model_limits import ModelLimitsProvider, RuntimeModelLimits


class TestRuntimeModelLimitsValidation(unittest.TestCase):
    def test_context_window_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeModelLimits(context_window=0)

    def test_max_output_tokens_must_be_positive_when_set(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeModelLimits(context_window=1000, max_output_tokens=0)

    def test_effective_percent_must_be_in_range(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeModelLimits(context_window=1000, effective_context_window_percent=0)
        with self.assertRaises(ValueError):
            RuntimeModelLimits(context_window=1000, effective_context_window_percent=101)

    def test_auto_compact_token_limit_must_be_positive_when_set(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeModelLimits(context_window=1000, auto_compact_token_limit=0)


class TestRuntimeModelLimitsDerived(unittest.TestCase):
    def test_effective_context_window_default_is_full_window(self) -> None:
        limits = RuntimeModelLimits(context_window=1000)
        self.assertEqual(limits.effective_context_window, 1000)

    def test_effective_context_window_applies_percent(self) -> None:
        limits = RuntimeModelLimits(context_window=1000, effective_context_window_percent=50)
        self.assertEqual(limits.effective_context_window, 500)

    def test_auto_compact_defaults_to_90_percent(self) -> None:
        # 未显式指定时按 Codex 兼容的 90% 默认值，且不超过有效窗口。
        limits = RuntimeModelLimits(context_window=1000)
        self.assertEqual(limits.effective_auto_compact_token_limit, 900)

    def test_auto_compact_explicit_capped_by_effective_window(self) -> None:
        limits = RuntimeModelLimits(
            context_window=1000,
            effective_context_window_percent=50,
            auto_compact_token_limit=800,
        )
        # 有效窗口为 500，显式 800 必须被夹到 500。
        self.assertEqual(limits.effective_auto_compact_token_limit, 500)


class TestModelLimitsProviderProtocol(unittest.TestCase):
    def test_implementer_satisfies_protocol(self) -> None:
        class StaticLimits:
            async def discover_model_limits(self, model: str) -> RuntimeModelLimits | None:
                return RuntimeModelLimits(context_window=128_000, max_output_tokens=8192)

        self.assertIsInstance(StaticLimits(), ModelLimitsProvider)

    def test_non_implementer_does_not_satisfy_protocol(self) -> None:
        class Empty:
            pass

        self.assertNotIsInstance(Empty(), ModelLimitsProvider)


if __name__ == "__main__":
    unittest.main(verbosity=2)
