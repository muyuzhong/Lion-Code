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


if __name__ == "__main__":
    unittest.main(verbosity=2)
