import itertools
import secrets

_counter = itertools.count(1)


def new_id(prefix: str = "") -> str:
    """生成进程内唯一 ID：单调计数器 + 随机后缀，不依赖时钟。"""
    if not isinstance(prefix, str):
        raise TypeError("prefix must be str")
    n = next(_counter)
    rand = secrets.token_hex(4)
    body = f"{n:012x}{rand}"
    return f"{prefix}_{body}" if prefix else body
