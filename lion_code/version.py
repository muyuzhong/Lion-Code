"""包版本助手。"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_DISTRIBUTION_NAME = "lion_code"
_UNKNOWN_VERSION = "0+unknown"


def current_version() -> str:
    """返回已安装的 lion_code 包版本;未安装(源码运行)时返回占位值。"""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _UNKNOWN_VERSION
