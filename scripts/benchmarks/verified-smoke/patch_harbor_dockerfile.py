#!/usr/bin/env python3
"""修补 Harbor 任务缓存的 environment Dockerfile：把容器内下载 uv 的步骤
换成走清华 PyPI 的 pip 安装（评测机/容器对 github.com 与 astral.sh 出网不稳，
对清华 PyPI 稳定可用）。

Harbor 从数据集下载任务时把 environment/Dockerfile 落到缓存目录
`<HARBOR_CACHE>/tasks/<hash>/<instance>/environment/Dockerfile`；该文件含
`RUN curl -LsSf https://astral.sh/uv/<ver>/install.sh | sh`，容器构建时
会因 github.com 超时失败。本脚本把该行替换为
`RUN pip install -i <index> uv==<ver>`（保留版本号），幂等，可重复执行。

用法：
  python patch_harbor_dockerfile.py <harbor-cache-dir>
  # 例如 ~/.cache/harbor 或 $WORK_DIR/harbor-home/.cache/harbor
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PYPI_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
_UV_CURL_RE = re.compile(
    r"RUN\s+curl\s+-[^\n]*astral\.sh/uv/([0-9.]+)/install\.sh\s*\|.*"
)


def _patch_one(dockerfile: Path) -> tuple[str, bool]:
    text = dockerfile.read_text(encoding="utf-8")
    match = _UV_CURL_RE.search(text)
    if match is None:
        return "no-uv-line", False
    version = match.group(1)
    replacement = f"RUN pip install -i {PYPI_INDEX} uv=={version}"
    new_text = _UV_CURL_RE.sub(replacement, text)
    if new_text == text:
        return "unchanged", False
    dockerfile.write_text(new_text, encoding="utf-8")
    return f"patched(uv=={version})", True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("harbor_cache_dir", type=Path, help="Harbor 缓存根目录")
    args = parser.parse_args()
    tasks_root = args.harbor_cache_dir / "tasks"
    if not tasks_root.is_dir():
        print(f"错误:不存在 Harbor tasks 缓存目录 {tasks_root}", file=sys.stderr)
        return 2

    changed: list[Path] = []
    for dockerfile in sorted(tasks_root.rglob("environment/Dockerfile")):
        status, is_changed = _patch_one(dockerfile)
        print(f"{status}: {dockerfile}")
        if is_changed:
            changed.append(dockerfile)
    print(f"共处理 {len(list(tasks_root.rglob('environment/Dockerfile')))} 个,"
          f"修改 {len(changed)} 个")
    return 0 if changed or True else 1


if __name__ == "__main__":
    raise SystemExit(main())
