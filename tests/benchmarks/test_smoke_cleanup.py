"""评测冒烟残留清理脚本(cleanup_smoke.sh)的子进程测试。

以临时结果根驱动脚本:
- 默认:删除可重建缓存目录,保留 run-* 证据目录;
- 干跑:不执行任何删除;
- 越界路径守卫:拒绝执行(rc=2);
另含 bash 语法检查。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "scripts" / "benchmarks" / "verified-smoke"
CLEANUP = SMOKE_DIR / "cleanup_smoke.sh"
WORK_DIR = "smoke-flask-5014"
CACHE_DIRS = ("harbor-home", "hf-home", "xdg-cache")


def run_cleanup(
    result_root: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SMOKE_RESULT_ROOT": str(result_root)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(CLEANUP)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def make_work_dir(result_root: Path) -> Path:
    work = result_root / WORK_DIR
    for name in CACHE_DIRS:
        (work / name).mkdir(parents=True, exist_ok=True)
        (work / name / "cache.bin").write_text("cache", encoding="utf-8")
    (work / "run-flask-5014-20260828-180351").mkdir(parents=True, exist_ok=True)
    (work / "run-flask-5014-20260828-180351" / "verified-report.json").write_text(
        "{}", encoding="utf-8"
    )
    return work


class TestCleanupSmoke:
    def test_default_removes_caches_keeps_run_evidence(self, tmp_path: Path) -> None:
        work = make_work_dir(tmp_path)
        result = run_cleanup(tmp_path)
        assert result.returncode == 0, result.stderr
        for name in CACHE_DIRS:
            assert not (work / name).exists()
        assert (
            work / "run-flask-5014-20260828-180351" / "verified-report.json"
        ).is_file()
        assert "run-* 证据目录未动" in result.stdout

    def test_dry_run_removes_nothing(self, tmp_path: Path) -> None:
        work = make_work_dir(tmp_path)
        result = run_cleanup(tmp_path, extra_env={"SMOKE_CLEAN_DRY_RUN": "1"})
        assert result.returncode == 0, result.stderr
        assert "[干跑]将删除" in result.stdout
        for name in CACHE_DIRS:
            assert (work / name / "cache.bin").is_file()

    def test_escape_guard_rejects_outside_result_root(self, tmp_path: Path) -> None:
        # smoke-flask-5014 是指向结果根之外(独立临时目录)的符号链接:
        # 解析后越界,守卫拒绝执行。
        import tempfile

        outside = Path(tempfile.mkdtemp(prefix="cleanup-outside-"))
        (tmp_path / WORK_DIR).symlink_to(outside, target_is_directory=True)
        result = run_cleanup(tmp_path)
        assert result.returncode == 2
        assert "越出结果根" in result.stderr
        assert not result.stdout.__contains__("删除:harbor-home")

    def test_missing_result_root_rejected(self, tmp_path: Path) -> None:
        result = run_cleanup(tmp_path / "missing")
        assert result.returncode == 2
        assert "不存在或不可访问" in result.stderr


class TestCleanupSyntax:
    def test_cleanup_smoke_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(CLEANUP)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
