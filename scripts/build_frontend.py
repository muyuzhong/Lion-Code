"""前端产物的唯一 rebuild 入口。

vite build 输出直接写入 ``lion_code/server/static``（package data，随
wheel/sdist 发布）。前端源码改动后运行本脚本并提交产物差异，保证产物可审计。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND_DIR = _REPO_ROOT / "frontend"
_STATIC_DIR = _REPO_ROOT / "lion_code" / "server" / "static"


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("未找到 npm，请先安装 Node.js", file=sys.stderr)
        return 1
    result = subprocess.run(
        [npm, "--prefix", str(_FRONTEND_DIR), "run", "build"],
        check=False,
        cwd=_REPO_ROOT,
    )
    if result.returncode != 0:
        print("前端构建失败", file=sys.stderr)
        return result.returncode
    if not (_STATIC_DIR / "index.html").is_file():
        print(f"构建产物缺失 index.html: {_STATIC_DIR}", file=sys.stderr)
        return 1
    print(f"前端产物已更新: {_STATIC_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
