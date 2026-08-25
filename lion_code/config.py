"""API 凭证的本地持久化（~/.lion-code/config.json），/model 与 CLI 启动共用。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".lion-code" / "config.json"
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def _resolve_path(path: Path | None) -> Path:
    # 运行时读取模块全局，测试可 monkeypatch CONFIG_PATH 注入 tmp_path。
    return CONFIG_PATH if path is None else path


def load_api_config(path: Path | None = None) -> dict:
    """读取已保存的 API 配置；缺失或损坏时返回空 dict。"""
    try:
        data = json.loads(_resolve_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config(config: dict, path: Path | None = None) -> None:
    """整 dict 原子写回：临时文件 + ``os.replace``，失败不留下半写状态。"""
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(f".{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp_path, target)
    # 凭证文件仅所有者可读写（Windows 上 chmod 仅影响只读位，0o600 语义不变）。
    try:
        target.parent.chmod(0o700)
        target.chmod(0o600)
    except OSError:
        pass


def save_api_config(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
    path: Path | None = None,
) -> None:
    """合并写回凭证四字段，保留 known_models 等扩展键。"""
    config = load_api_config(path)
    config.update(
        {
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
        }
    )
    write_config(config, path)


def resolve_api_credentials(
    *,
    env: dict[str, str] | None = None,
    allow_placeholder: bool = False,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """按优先级解析 API 凭证：环境变量 > 本地配置 > 占位端点。

    env 只覆盖 api_key 与对应 base_url（同时决定 Provider 通道）；已保存的
    ``model`` 始终从本地配置读回，避免 env 凭证存在时重启丢失模型选择。
    """
    source_env = os.environ if env is None else env
    saved = load_api_config(config_path)

    api_key: str | None = None
    api_base: str | None = None
    use_openai = False

    if source_env.get("OPENAI_API_KEY") and source_env.get("OPENAI_BASE_URL"):
        api_key = source_env["OPENAI_API_KEY"]
        api_base = source_env["OPENAI_BASE_URL"]
        use_openai = True
    elif source_env.get("ANTHROPIC_API_KEY"):
        api_key = source_env["ANTHROPIC_API_KEY"]
        api_base = source_env.get("ANTHROPIC_BASE_URL") or None
        use_openai = False
    elif source_env.get("OPENAI_API_KEY"):
        api_key = source_env["OPENAI_API_KEY"]
        api_base = source_env.get("OPENAI_BASE_URL") or None
        use_openai = True

    # model 独立于凭证来源：env 只覆盖通道与 key，模型选择始终取保存值。
    model = str(saved["model"]) if saved.get("model") else None

    if api_key is None:
        if saved.get("api_key"):
            api_key = saved["api_key"]
            use_openai = saved.get("provider") == "openai"
            if use_openai:
                # 保存的 OpenAI 配置没有自定义端点时仍需保持 OpenAI 通道。
                api_base = saved.get("base_url") or _DEFAULT_OPENAI_BASE_URL
            else:
                api_base = saved.get("base_url") or None

    if api_key is None and allow_placeholder:
        use_openai = True
        api_base = api_base or _DEFAULT_OPENAI_BASE_URL

    if use_openai and api_base is None:
        api_base = _DEFAULT_OPENAI_BASE_URL

    return {
        "api_key": api_key,
        "api_base": api_base,
        "use_openai": use_openai,
        "model": model,
    }
