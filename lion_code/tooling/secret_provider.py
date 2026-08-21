"""Secret Boundary 的登记与指纹层：明文值不出本模块。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path

# 低于该长度的值不注册：短值会把大量普通 token 误替换为 ***
MIN_SECRET_LENGTH = 8

_SECRET_NAME_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def _hmac_hex(key: bytes, text: str) -> str:
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()


def load_or_create_key(key_file: Path) -> bytes:
    """读取或首次生成 HMAC 密钥；权限收紧尽力而为（Windows 无完整 POSIX 语义）。"""
    if key_file.exists():
        data = key_file.read_bytes().strip()
        if data:
            return data
    key = secrets.token_hex(32).encode("ascii")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    try:
        key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in content.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        value = value.strip().strip("'\"")
        if value:
            values[key.strip()] = value
    return values


def _secret_env_values(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environ.items()
        if name.upper().endswith(_SECRET_NAME_SUFFIXES)
    }


class SecretStore:
    """登记值为 HMAC 指纹族（原值 + base64 变体），只对外暴露 matches 查询。"""

    def __init__(self, values: Mapping[str, str], key: bytes) -> None:
        self._key = key
        self._fingerprints = frozenset(
            digest
            for value in values.values()
            if len(value) >= MIN_SECRET_LENGTH
            for digest in (
                _hmac_hex(key, value),
                _hmac_hex(
                    key,
                    base64.b64encode(value.encode("utf-8")).decode("ascii"),
                ),
            )
        )

    def fingerprints(self) -> frozenset[str]:
        return self._fingerprints

    def matches(self, text: str) -> bool:
        return _hmac_hex(self._key, text) in self._fingerprints


def load_secret_store(
    *,
    workspace: Path,
    key_file: Path,
    environ: Mapping[str, str] | None = None,
) -> SecretStore:
    """聚合 workspace `.env` 全量键值与进程环境变量中的凭据类条目。

    只读 `.env` 本体：`.env.example` 之类模板文件装的是占位符，
    注册会产生大面积误 redact。
    """
    values = _parse_env_file(workspace / ".env")
    values.update(_secret_env_values(environ if environ is not None else os.environ))
    return SecretStore(values, load_or_create_key(key_file))
