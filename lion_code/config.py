"""API 凭证的本地持久化（~/.lion-code/config.json），/model 与 CLI 启动共用。"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".lion-code" / "config.json"


def load_api_config() -> dict:
    """读取已保存的 API 配置；缺失或损坏时返回空 dict。"""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_api_config(*, provider: str, model: str, api_key: str, base_url: str = "") -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }, indent=2))
    # 凭证文件仅所有者可读写（Windows 上 chmod 仅影响只读位，0o600 语义不变）。
    try:
        CONFIG_PATH.parent.chmod(0o700)
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass
