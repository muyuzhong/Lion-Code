"""评测冒烟模板守卫测试:smoke.env 权限/凭证校验与脱敏静态断言。

`run_smoke.sh` 为面向评测主机的 bash 模板,本测试以子进程方式驱动其
前置校验路径(SMOKE_CHECK_ONLY=1,绝不触发真实评测):
- 凭证文件缺失 → 拒绝启动(rc=2);
- 权限过宽(0644)且属主为当前用户 → 自动修复为 600 后继续;
- 属主非当前用户 → 拒绝启动(rc=2,仅 root 环境可构造,其余跳过);
- 必填变量缺失 → 拒绝启动(rc=2);
另含 bash 语法检查与模板脱敏静态断言(无本机绝对路径/个人字面量/
样例密钥),防未来改动回退。
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "scripts" / "benchmarks" / "verified-smoke"
RUN_SMOKE = SMOKE_DIR / "run_smoke.sh"

ENV_FILE_CONTENT = (
    "OPENAI_API_KEY=dummy-key\nLION_MODEL=dummy-model\nOPIK_WORKSPACE=dummy-workspace\n"
)


def run_smoke(
    env_file: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """以 SMOKE_CHECK_ONLY=1 驱动 run_smoke.sh,返回子进程结果。"""
    env = {
        **os.environ,
        "SMOKE_ENV_FILE": str(env_file),
        "SMOKE_RESULT_ROOT": str(env_file.parent),
        "SMOKE_CHECK_ONLY": "1",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(RUN_SMOKE)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestEnvGuard:
    def test_missing_env_file_rejected(self, tmp_path: Path) -> None:
        result = run_smoke(tmp_path / "does-not-exist.env")
        assert result.returncode == 2
        assert "缺少" in result.stderr
        assert "smoke.env.example" in result.stderr

    def test_loose_permissions_fixed_to_600(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text(ENV_FILE_CONTENT, encoding="utf-8")
        env_file.chmod(0o644)
        result = run_smoke(env_file)
        assert result.returncode == 0, result.stderr
        assert "check-only" in result.stdout
        # 权限不变量:启动后必须恒为 600
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    @pytest.mark.skipif(os.geteuid() != 0, reason="chown 到其他属主需要 root")
    def test_foreign_owner_rejected(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text(ENV_FILE_CONTENT, encoding="utf-8")
        env_file.chmod(0o600)
        os.chown(env_file, 65534, -1)
        result = run_smoke(env_file)
        assert result.returncode == 2
        assert "属主" in result.stderr

    def test_required_var_missing_rejected(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text("OPENAI_API_KEY=dummy-key\n", encoding="utf-8")
        env_file.chmod(0o600)
        result = run_smoke(env_file)
        assert result.returncode == 2
        assert "未填写 LION_MODEL" in result.stderr

    def test_optional_base_url_passthrough(self, tmp_path: Path) -> None:
        """可选变量 OPENAI_BASE_URL 不缺失时校验仍通过。"""
        env_file = tmp_path / "smoke.env"
        env_file.write_text(
            ENV_FILE_CONTENT + "OPENAI_BASE_URL=https://example.invalid/v1\n",
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        result = run_smoke(env_file)
        assert result.returncode == 0, result.stderr


class TestBashSyntax:
    def test_run_smoke_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(RUN_SMOKE)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr


class TestDesensitization:
    """模板入库后的脱敏静态断言:无本机路径/个人字面量/样例密钥。"""

    TEMPLATE_FILES = (
        "run_smoke.sh",
        "build_catalog.py",
        "build_manifest.py",
        "smoke.env.example",
        "README.md",
    )
    FORBIDDEN = (r"/home/", r"muyuzhong", r"sk-[A-Za-z0-9]{16,}")

    @pytest.mark.parametrize("filename", TEMPLATE_FILES)
    @pytest.mark.parametrize("pattern", FORBIDDEN)
    def test_no_forbidden_content(self, filename: str, pattern: str) -> None:
        text = (SMOKE_DIR / filename).read_text(encoding="utf-8")
        regex = re.compile(pattern)
        assert regex.search(text) is None, (
            f"{filename} 含脱敏禁止内容(匹配 {pattern!r})"
        )
