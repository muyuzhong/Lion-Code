"""Web 发布物验证：wheel 内容 + 安装态 smoke。

1. 构建 wheel，断言 ``lion_code/server/static`` 内含 index.html 与 hashed assets；
2. ``pip install --no-deps --target`` 到独立目录，以 ``PYTHONPATH`` 从该安装态
   import ``lion_code``，定位 package resource 静态产物（依赖来自当前环境，
   隔离的是包本体——验证发布物布局，不验证依赖解析）。

用法： ``python scripts/verify_web_delivery.py``。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STATIC_PREFIX = "lion_code/server/static/"


def build_wheel(workdir: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", workdir, "."],
        check=True,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    wheels = sorted(workdir.glob("lion_code-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"期望恰好一个 wheel，实际: {wheels}")
    return wheels[0]


def assert_wheel_static(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    has_index = f"{_STATIC_PREFIX}index.html" in names
    hashed = [
        n
        for n in names
        if n.startswith(f"{_STATIC_PREFIX}assets/") and n.endswith(".js")
    ]
    if not has_index:
        raise SystemExit(f"wheel 缺少 {_STATIC_PREFIX}index.html")
    if not hashed:
        raise SystemExit(f"wheel 缺少 hashed assets（{_STATIC_PREFIX}assets/*.js）")
    print(f"wheel 静态产物: index.html + {len(hashed)} 个 js asset")


def installed_layout_smoke(wheel: Path, workdir: Path) -> None:
    install_dir = workdir / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_dir),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = (
        "import importlib.resources, json\n"
        "import lion_code\n"
        "from lion_code.server.app import _default_static_dir\n"
        "assert 'site' in lion_code.__file__.replace('\\\\', '/'), lion_code.__file__\n"
        "static_dir = _default_static_dir()\n"
        "assert (static_dir / 'index.html').is_file(), static_dir\n"
        "print(json.dumps({'static_dir': str(static_dir)}))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(install_dir)}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"安装态 smoke 失败:\n{result.stdout}\n{result.stderr}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if "site" not in payload["static_dir"].replace("\\", "/"):
        raise SystemExit(f"静态产物未解析到安装目录: {payload}")
    print(f"安装态可定位静态产物: {payload['static_dir']}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lion-web-delivery-") as tmp:
        workdir = Path(tmp)
        wheel = build_wheel(workdir / "wheel")
        assert_wheel_static(wheel)
        installed_layout_smoke(wheel, workdir)
    print("Web 发布物验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
