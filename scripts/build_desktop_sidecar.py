"""构建 Electron extraResources 使用的 PyInstaller onedir sidecar。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIST_PATH = _REPO_ROOT / "desktop" / "sidecar"
_WORK_PATH = _REPO_ROOT / "build" / "pyinstaller-sidecar"
_SPEC_PATH = _REPO_ROOT / "scripts" / "lion-sidecar.spec"


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(_DIST_PATH),
            "--workpath",
            str(_WORK_PATH),
            str(_SPEC_PATH),
        ],
        cwd=_REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    executable = _DIST_PATH / "lion-sidecar" / "lion-sidecar.exe"
    if not executable.is_file():
        print(f"sidecar 构建产物缺失: {executable}", file=sys.stderr)
        return 1
    print(f"sidecar 构建完成: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
