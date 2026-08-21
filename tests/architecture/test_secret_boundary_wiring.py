"""PR-S2 接线门禁：sanitizer 必须落在 post 链首位，且可整体关闭。"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from lion_code.composition import (
    AgentConfig,
    MinimalProfile,
    RuntimeBindings,
    ToolBindings,
    build_agent_composition,
)
from lion_code.tooling.output_sanitizer import OutputSanitizerMiddleware
from lion_code.tooling.secret_provider import SecretStore


def _composition(tmp_path, monkeypatch, tool_bindings: ToolBindings):
    monkeypatch.chdir(tmp_path)
    config = AgentConfig(api_key="test-key", terminal_output=False)
    provider = Mock()
    provider.aclose = AsyncMock()
    with patch(
        "lion_code.composition.agent_builder.create_provider",
        return_value=provider,
    ):
        return build_agent_composition(
            MinimalProfile(tools=()),
            config=config,
            bindings=RuntimeBindings(tool=tool_bindings),
        )


def test_sanitizer_is_first_post_middleware(tmp_path, monkeypatch) -> None:
    composition = _composition(
        tmp_path,
        monkeypatch,
        ToolBindings(secret_store=SecretStore({"API_KEY": "value-long-enough"}, b"k")),
    )
    post = [
        item for item in composition.tooling.runtime.middleware if item.phase == "post"
    ]
    assert post, "post 链不应为空"
    assert isinstance(post[0], OutputSanitizerMiddleware)
    audit_last = type(post[-1]).__name__
    assert audit_last == "AuditMiddleware"


def test_secret_boundary_can_be_disabled(tmp_path, monkeypatch) -> None:
    composition = _composition(
        tmp_path, monkeypatch, ToolBindings(enable_secret_boundary=False)
    )
    assert not any(
        isinstance(item, OutputSanitizerMiddleware)
        for item in composition.tooling.runtime.middleware
    )
