"""验证 Windows 桌面发布源与 PyInstaller sidecar 布局。"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tarfile
import tempfile
import threading
import tomllib
import urllib.request
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REMOVED_WEB_PATHS = (
    Path("frontend"),
    Path("lion_code/server/static"),
    Path("scripts/build_frontend.py"),
    Path("scripts/verify_web_delivery.py"),
)


def verify_source_layout(root: Path) -> None:
    package = json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    desktop_version = package.get("version")
    python_version = project.get("project", {}).get("version")
    if desktop_version != python_version:
        raise ValueError(
            f"桌面与 Python 版本不一致: {desktop_version!r} != {python_version!r}"
        )

    build = package.get("build", {})
    resources = build.get("extraResources", [])
    expected = {
        "from": "sidecar/lion-sidecar",
        "to": "sidecar",
        "filter": ["**/*"],
    }
    if expected not in resources:
        raise ValueError("electron-builder 缺少受控 sidecar extraResources 映射")
    if "THIRD_PARTY_NOTICES.md" not in build.get("files", []):
        raise ValueError("桌面发布物缺少 THIRD_PARTY_NOTICES.md")
    for relative in _REMOVED_WEB_PATHS:
        path = root / relative
        if path.is_file() or (
            path.is_dir() and any(candidate.is_file() for candidate in path.rglob("*"))
        ):
            raise ValueError(f"旧 Web 交付路径仍存在: {relative.as_posix()}")


def verify_sidecar_layout(sidecar_dir: Path) -> None:
    executable = sidecar_dir / "lion-sidecar.exe"
    if not executable.is_file():
        raise ValueError(f"sidecar 可执行文件缺失: {executable}")
    sources = sorted(sidecar_dir.rglob("*.py"))
    if sources:
        raise ValueError(f"sidecar 发布物包含 Python 源码: {sources[0]}")


def smoke_sidecar(executable: Path) -> None:
    """启动打包 sidecar、探测鉴权 API，并验证 stdin 优雅退出。"""
    with tempfile.TemporaryDirectory(prefix="lion-sidecar-smoke-") as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        state_home = root / "state"
        workspace.mkdir()
        state_home.mkdir()
        environment = os.environ.copy()
        environment["LION_SIDECAR_STATE_HOME"] = str(state_home)
        process = subprocess.Popen(
            [str(executable), "--workspace", str(workspace)],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdout is not None
        assert process.stdin is not None
        lines: queue.Queue[str] = queue.Queue(maxsize=1)
        threading.Thread(
            target=lambda: lines.put(process.stdout.readline()),
            daemon=True,
            name="lion-sidecar-smoke-ready",
        ).start()
        try:
            try:
                ready_line = lines.get(timeout=30)
            except queue.Empty as exc:
                raise ValueError("打包 sidecar 未在 30 秒内就绪") from exc
            ready = _parse_ready_record(ready_line)
            request = urllib.request.Request(
                f"http://127.0.0.1:{ready['port']}/api/sessions",
                headers={"Authorization": f"Bearer {ready['capability']}"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise ValueError(f"打包 sidecar API 探测失败: {response.status}")
            process.stdin.write("shutdown\n")
            process.stdin.flush()
            exit_code = process.wait(timeout=20)
            if exit_code != 0:
                raise ValueError(f"打包 sidecar 退出码异常: {exit_code}")
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            assert process.stderr is not None
            detail = process.stderr.read()[-2000:]
            if detail:
                print(detail, file=sys.stderr)
            raise


def _parse_ready_record(line: str) -> dict[str, object]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"打包 sidecar ready 记录不是 JSON: {line!r}") from exc
    if (
        not isinstance(record, dict)
        or record.get("type") != "ready"
        or record.get("version") != 1
        or not isinstance(record.get("port"), int)
        or not isinstance(record.get("capability"), str)
        or not record["capability"]
    ):
        raise ValueError(f"打包 sidecar ready 记录无效: {record!r}")
    return record


def verify_python_distributions(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="lion-dist-verify-") as temp_dir:
        output = Path(temp_dir)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--sdist",
                "--outdir",
                str(output),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        sdist = next(output.glob("*.tar.gz"), None)
        if sdist is None:
            raise ValueError("Python sdist 构建产物缺失")
        with tarfile.open(sdist, "r:gz") as archive:
            _reject_web_members(archive.getnames(), sdist.name)
            source_root = output / "source"
            archive.extractall(source_root, filter="data")
        source = next(path for path in source_root.iterdir() if path.is_dir())
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(output),
                str(source),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        wheel = next(output.glob("*.whl"), None)
        if wheel is None:
            raise ValueError("Python wheel 构建产物缺失")
        with zipfile.ZipFile(wheel) as archive:
            _reject_web_members(archive.namelist(), wheel.name)


def _reject_web_members(members: list[str], artifact: str) -> None:
    for member in members:
        normalized = member.replace("\\", "/")
        if "/server/static/" in normalized or "/frontend/" in normalized:
            raise ValueError(f"{artifact} 仍包含旧 Web 资源: {member}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_REPO_ROOT)
    parser.add_argument(
        "--sidecar-dir",
        type=Path,
        default=_REPO_ROOT / "desktop/sidecar/lion-sidecar",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verify_source_layout(args.root.resolve())
    sidecar_dir = args.sidecar_dir.resolve()
    verify_sidecar_layout(sidecar_dir)
    smoke_sidecar(sidecar_dir / "lion-sidecar.exe")
    verify_python_distributions(args.root.resolve())
    print("桌面发布布局验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
