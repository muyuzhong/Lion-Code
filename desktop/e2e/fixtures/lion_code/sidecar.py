"""只实现 ready/stdin shutdown 的测试进程，不进入生产构建。"""

import json
import os
import sys
from pathlib import Path


def _record(event: str) -> None:
    log_path = os.environ.get("LION_FAKE_SIDECAR_LOG")
    if log_path:
        with Path(log_path).open("a", encoding="utf-8") as stream:
            stream.write(f"{event}:{os.getpid()}\n")


_record("start")
print(
    json.dumps(
        {"type": "ready", "version": 1, "port": 43123, "capability": "T" * 32}
    ),
    flush=True,
)
if sys.stdin.readline().strip() == "shutdown":
    _record("stop")
