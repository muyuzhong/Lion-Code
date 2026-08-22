"""API 凭证的本地持久化（~/.lion-code/config.json），/model 与 CLI 启动共用。"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".lion-code" / "config.json"


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
