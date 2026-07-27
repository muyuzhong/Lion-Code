"""``create_provider`` 路由测试：按 ``api_base`` 选择适配器并归一化 base_url。"""

from __future__ import annotations

import unittest

from lion_code.providers.anthropic import AnthropicProvider
from lion_code.providers.factory import create_provider
from lion_code.providers.openai_compatible import OpenAICompatibleProvider


class TestCreateProvider(unittest.TestCase):
    def test_api_base_routes_to_openai_compatible(self) -> None:
        provider = create_provider(api_key="k", api_base="https://example.test/v1/")
        self.assertIsInstance(provider, OpenAICompatibleProvider)
        # 末尾斜杠被去掉。
        self.assertEqual(provider._config.base_url, "https://example.test/v1")
        self.assertEqual(provider._config.max_tokens, 16_384)

    def test_no_api_base_routes_to_anthropic_default(self) -> None:
        provider = create_provider(api_key="k")
        self.assertIsInstance(provider, AnthropicProvider)
        self.assertEqual(provider._config.base_url, "https://api.anthropic.com/v1")

    def test_anthropic_base_url_override_strips_trailing_slash(self) -> None:
        provider = create_provider(api_key="k", anthropic_base_url="https://custom.test/v1/")
        self.assertIsInstance(provider, AnthropicProvider)
        self.assertEqual(provider._config.base_url, "https://custom.test/v1")


class TestCreateProviderThinkingLevel(unittest.TestCase):
    def test_none_leaves_anthropic_thinking_unset(self) -> None:
        provider = create_provider(api_key="k")
        self.assertIsNone(provider._config.thinking_budget_tokens)
        self.assertEqual(provider._config.thinking_mode, "budget")

    def test_anthropic_high_sets_budget_tokens(self) -> None:
        provider = create_provider(api_key="k", thinking_level="high")
        self.assertEqual(provider._config.thinking_budget_tokens, 8192)
        self.assertEqual(provider._config.thinking_mode, "budget")

    def test_anthropic_off_explicitly_disables(self) -> None:
        provider = create_provider(api_key="k", thinking_level="off")
        self.assertEqual(provider._config.thinking_mode, "disabled")
        self.assertIsNone(provider._config.thinking_budget_tokens)

    def test_anthropic_level_is_normalized(self) -> None:
        provider = create_provider(api_key="k", thinking_level="  Medium ")
        self.assertEqual(provider._config.thinking_budget_tokens, 4096)

    def test_openai_high_sets_reasoning_effort(self) -> None:
        provider = create_provider(
            api_key="k", api_base="https://example.test/v1", thinking_level="high"
        )
        self.assertEqual(provider._config.reasoning_effort, "high")

    def test_openai_off_maps_to_none_effort(self) -> None:
        provider = create_provider(
            api_key="k", api_base="https://example.test/v1", thinking_level="off"
        )
        self.assertEqual(provider._config.reasoning_effort, "none")

    def test_openai_none_leaves_reasoning_effort_unset(self) -> None:
        provider = create_provider(api_key="k", api_base="https://example.test/v1")
        self.assertIsNone(provider._config.reasoning_effort)


if __name__ == "__main__":
    unittest.main(verbosity=2)
