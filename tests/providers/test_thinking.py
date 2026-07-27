"""Thinking 档位纯逻辑测试:词汇、归一化、循环、coerce、Provider 参数映射。"""

from __future__ import annotations

import unittest

from lion_code.providers.thinking import (
    DEFAULT_THINKING_LEVEL,
    THINKING_LEVELS,
    anthropic_budget_tokens_for_level,
    coerce_thinking_level,
    next_thinking_level,
    normalize_thinking_level,
    openai_reasoning_effort_for_level,
    provider_default_thinking_level,
    provider_thinking_levels,
)


class TestThinkingVocabulary(unittest.TestCase):
    def test_levels_are_six_off_to_xhigh(self) -> None:
        self.assertEqual(
            THINKING_LEVELS, ("off", "minimal", "low", "medium", "high", "xhigh")
        )

    def test_default_is_medium(self) -> None:
        self.assertEqual(DEFAULT_THINKING_LEVEL, "medium")


class TestNormalize(unittest.TestCase):
    def test_none_falls_back_to_default(self) -> None:
        self.assertEqual(normalize_thinking_level(None), "medium")

    def test_strips_and_lowercases(self) -> None:
        self.assertEqual(normalize_thinking_level("  HIGH "), "high")
        self.assertEqual(normalize_thinking_level("XHigh"), "xhigh")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_thinking_level("ultra")
        # 旧 SDK 词汇不属于新档位,normalize 必须拒绝(只有 coerce 容忍)。
        with self.assertRaises(ValueError):
            normalize_thinking_level("disabled")


class TestCoerce(unittest.TestCase):
    def test_new_vocab_passthrough(self) -> None:
        self.assertEqual(coerce_thinking_level("low"), "low")
        self.assertEqual(coerce_thinking_level("  Medium "), "medium")

    def test_legacy_disabled_maps_to_off(self) -> None:
        self.assertEqual(coerce_thinking_level("disabled"), "off")

    def test_legacy_adaptive_and_enabled_map_to_medium(self) -> None:
        self.assertEqual(coerce_thinking_level("adaptive"), "medium")
        self.assertEqual(coerce_thinking_level("enabled"), "medium")

    def test_unknown_falls_back_to_off(self) -> None:
        self.assertEqual(coerce_thinking_level("bogus"), "off")

    def test_none_falls_back_to_default(self) -> None:
        self.assertEqual(coerce_thinking_level(None), "medium")


class TestNextLevel(unittest.TestCase):
    def test_cycles_forward(self) -> None:
        self.assertEqual(next_thinking_level("off"), "minimal")
        self.assertEqual(next_thinking_level("medium"), "high")

    def test_wraps_around(self) -> None:
        self.assertEqual(next_thinking_level("xhigh"), "off")

    def test_current_not_in_available_falls_back_to_first(self) -> None:
        # current="xhigh" 已被裁剪;available 不含它 -> 回落到首档(对齐 Tau)。
        available = ("off", "low", "high")
        self.assertEqual(next_thinking_level("xhigh", available), "off")

    def test_empty_available_keeps_current(self) -> None:
        self.assertEqual(next_thinking_level("medium", ()), "medium")


class TestAnthropicMapping(unittest.TestCase):
    def test_off_disables_thinking(self) -> None:
        self.assertIsNone(anthropic_budget_tokens_for_level("off"))

    def test_budget_tokens_per_level(self) -> None:
        self.assertEqual(anthropic_budget_tokens_for_level("minimal"), 1024)
        self.assertEqual(anthropic_budget_tokens_for_level("low"), 2048)
        self.assertEqual(anthropic_budget_tokens_for_level("medium"), 4096)
        self.assertEqual(anthropic_budget_tokens_for_level("high"), 8192)
        self.assertEqual(anthropic_budget_tokens_for_level("xhigh"), 16384)


class TestOpenAIMapping(unittest.TestCase):
    def test_off_maps_to_none_effort(self) -> None:
        self.assertEqual(openai_reasoning_effort_for_level("off"), "none")

    def test_other_levels_passthrough(self) -> None:
        for level in ("minimal", "low", "medium", "high", "xhigh"):
            self.assertEqual(openai_reasoning_effort_for_level(level), level)


class TestProviderLevels(unittest.TestCase):
    def test_both_backends_expose_all_six(self) -> None:
        for kind in ("anthropic", "openai-compatible"):
            self.assertEqual(provider_thinking_levels(kind), THINKING_LEVELS)

    def test_default_is_medium_for_both_backends(self) -> None:
        for kind in ("anthropic", "openai-compatible"):
            self.assertEqual(provider_default_thinking_level(kind), "medium")


if __name__ == "__main__":
    unittest.main(verbosity=2)
