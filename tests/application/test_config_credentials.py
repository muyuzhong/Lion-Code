"""config.py 凭证解析的四象限回归测试。

覆盖 resolve_api_credentials 的 env/config/占位优先级，重点是
"env 凭证存在时已保存 model 不被丢弃"（桌面客户端重启丢失模型配置的回归）。
"""

from __future__ import annotations

from pathlib import Path

from lion_code.config import resolve_api_credentials, save_api_config


def _write_config(
    tmp_path: Path, *, provider: str, model: str, api_key: str, base_url: str = ""
) -> None:
    save_api_config(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        path=tmp_path / "config.json",
    )


def test_no_credentials_no_config_placeholder(tmp_path: Path) -> None:
    result = resolve_api_credentials(
        env={}, allow_placeholder=True, config_path=tmp_path / "config.json"
    )
    assert result["api_key"] is None
    assert result["model"] is None
    assert result["use_openai"] is True
    assert result["api_base"] == "https://api.openai.com/v1"


def test_config_only_without_env(tmp_path: Path) -> None:
    _write_config(
        tmp_path, provider="anthropic", model="claude-sonnet-4-6", api_key="sk-config"
    )
    result = resolve_api_credentials(
        env={}, allow_placeholder=False, config_path=tmp_path / "config.json"
    )
    assert result["api_key"] == "sk-config"
    assert result["model"] == "claude-sonnet-4-6"
    assert result["use_openai"] is False


def test_saved_openai_without_base_url_uses_default_endpoint(tmp_path: Path) -> None:
    _write_config(tmp_path, provider="openai", model="gpt-5", api_key="sk-config")

    result = resolve_api_credentials(
        env={}, allow_placeholder=False, config_path=tmp_path / "config.json"
    )

    assert result == {
        "api_key": "sk-config",
        "api_base": "https://api.openai.com/v1",
        "use_openai": True,
        "model": "gpt-5",
    }


def test_env_key_keeps_saved_model(tmp_path: Path) -> None:
    """env 凭证存在时，已保存 model 仍从 config 读回（R1 回归）。"""
    _write_config(
        tmp_path, provider="anthropic", model="claude-sonnet-4-6", api_key="sk-config"
    )
    result = resolve_api_credentials(
        env={
            "OPENAI_API_KEY": "sk-env",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        },
        allow_placeholder=False,
        config_path=tmp_path / "config.json",
    )
    assert result["api_key"] == "sk-env"
    assert result["api_base"] == "https://api.openai.com/v1"
    assert result["use_openai"] is True
    assert result["model"] == "claude-sonnet-4-6"


def test_env_anthropic_keeps_saved_model(tmp_path: Path) -> None:
    _write_config(tmp_path, provider="openai", model="gpt-5", api_key="sk-config")
    result = resolve_api_credentials(
        env={"ANTHROPIC_API_KEY": "sk-anthropic-env"},
        allow_placeholder=False,
        config_path=tmp_path / "config.json",
    )
    assert result["api_key"] == "sk-anthropic-env"
    assert result["use_openai"] is False
    assert result["model"] == "gpt-5"


def test_missing_config_file_returns_defaults(tmp_path: Path) -> None:
    result = resolve_api_credentials(
        env={}, allow_placeholder=False, config_path=tmp_path / "config.json"
    )
    assert result["api_key"] is None
    assert result["model"] is None
    assert result["use_openai"] is False
