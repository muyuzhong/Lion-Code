import logging


def get_logger(name: str) -> logging.Logger:
    """返回 nanoagent 命名空间下的 logger；不安装 handler，具体日志策略由 harness 配置。"""
    if not isinstance(name, str):
        raise TypeError("name must be str")
    return logging.getLogger("nanoagent" if name == "" else f"nanoagent.{name}")
