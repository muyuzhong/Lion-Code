"""Harbor v0.22.0 installed-agent：在任务容器内调用现有 Lion worker。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

try:
    from harbor.agents.installed.base import BaseInstalledAgent
except ModuleNotFoundError:

    class BaseInstalledAgent:  # type: ignore[no-redef]
        """让未安装 Harbor 的 Windows 单元测试仍可导入 benchmark 包。"""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Harbor 0.22.0 is required for the installed-agent")


class LionInstalledAgent(BaseInstalledAgent):
    """把 Harbor 环境中的单题任务交给已安装的 Lion Agent.run。"""

    VERSION = "lion-installed-agent/v1"
    MODEL_CONNECTION: ClassVar[None] = None
    _REMOTE_ROOT = "/installed-agent/benchmarks/agent_e2e"
    _REMOTE_REQUEST = "/installed-agent/request.json"
    _REMOTE_PYTHON312 = "/opt/lion-py"
    _LOG_ROOT = "/logs/agent"
    # 容器内 pip 解析 Lion wheel 依赖时默认走 pypi.org,评测机对其出网不通
    # 会卡到 setup 超时;固定走清华镜像。
    _PYPI_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
    # swebench 任务镜像内置 Python 3.11,而 Lion 要求 >=3.12(PEP 695 语法)。
    # 固定 python-build-standalone 发布资产(URL 不可变),免编译、免改镜像。
    _PYTHON312_URL = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        "20260825/cpython-3.12.14%2B20260825-x86_64-unknown-linux-gnu-install_only.tar.gz"
    )
    _SOURCE_FILES = (
        "agent_worker.py",
        "backend.py",
        "evidence.py",
        "analysis_trace.py",
        "models.py",
        "trace.py",
        "variant_injection.py",
        "worker_entrypoint.py",
    )

    def __init__(
        self,
        logs_dir: Path,
        *,
        wheel_path: str | Path,
        manifest_json: str | Mapping[str, Any],
        task_json: str | Mapping[str, Any],
        attempt: int = 1,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._wheel_path = Path(wheel_path)
        if not self._wheel_path.is_absolute():
            self._wheel_path = (Path.cwd() / self._wheel_path).resolve()
        self._manifest_json = _json_text(manifest_json)
        self._task_json = _json_text(task_json)
        self._attempt = int(attempt)
        harbor_env = kwargs.pop("extra_env", None) or {}
        credential_names = _credential_env_names(self._manifest_json)
        credential_env = {
            name: harbor_env[name] if name in harbor_env else os.environ[name]
            for name in credential_names
            if name in harbor_env or os.environ.get(name)
        }
        super().__init__(
            logs_dir=logs_dir,
            model_name=model_name,
            extra_env=credential_env,
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        """返回 Harbor 记录中的稳定 agent 名称。"""

        return "lion-installed-agent"

    def version(self) -> str:
        """返回 installed-agent 自身版本，而不是 Lion wheel 版本。"""

        return self.VERSION

    async def install(self, environment: Any) -> None:
        """安装固定 wheel，并上传最小 worker 源文件集合。"""

        if not self._wheel_path.is_file():
            raise FileNotFoundError(f"Lion wheel not found: {self._wheel_path}")
        await self.ensure_system_dependencies(
            environment,
            ("git", "python3", "python_pip"),
        )
        await environment.exec(
            command=f"mkdir -p {self._REMOTE_ROOT}",
            user="root",
        )
        await self._upload_agent_owned_file(
            environment,
            self._wheel_path,
            f"/installed-agent/{self._wheel_path.name}",
        )
        source_root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix="lion-harbor-package-") as directory:
            temporary_root = Path(directory)
            for package_path in (
                temporary_root / "__init__.py",
                temporary_root / "benchmarks_init.py",
            ):
                package_path.write_text("", encoding="utf-8")
            await self._upload_agent_owned_file(
                environment,
                temporary_root / "benchmarks_init.py",
                "/installed-agent/benchmarks/__init__.py",
            )
            await self._upload_agent_owned_file(
                environment,
                temporary_root / "__init__.py",
                f"{self._REMOTE_ROOT}/__init__.py",
            )
        for filename in self._SOURCE_FILES:
            await self._upload_agent_owned_file(
                environment,
                source_root / filename,
                f"{self._REMOTE_ROOT}/{filename}",
            )
        await self._install_python312(environment)
        await self.exec_as_root(
            environment,
            command=(
                f"{self._REMOTE_PYTHON312}/bin/python3 -m pip install --no-cache-dir "
                f"-i {self._PYPI_INDEX} /installed-agent/{self._wheel_path.name}"
            ),
        )

    async def _install_python312(self, environment: Any) -> None:
        """在任务容器内安装固定版本的独立 Python 3.12。

        swebench 镜像自带 Python 3.11,而 Lion 要求 >=3.12;python-build-standalone
        的 install_only 资产免编译、URL 内容寻址不变。优先使用评测主机缓存的
        tarball(host → 容器上传远快于容器外网下载,规避 Harbor 360s setup 上限),
        缓存缺失时回退容器内标准库下载。解压到 /opt/lion-py 供 wheel 与 worker 共用。
        """
        cached = self._cached_python312_tarball()
        if cached is not None and cached.is_file():
            await self.exec_as_root(
                environment,
                command="mkdir -p /tmp && rm -f /tmp/lion-py312.tar.gz",
            )
            await environment.upload_file(cached, "/tmp/lion-py312.tar.gz")
        else:
            with tempfile.TemporaryDirectory(
                prefix="lion-harbor-python312-"
            ) as directory:
                fetch_script = Path(directory) / "fetch_lion_py312.py"
                fetch_script.write_text(
                    "import urllib.request\n"
                    f"urllib.request.urlretrieve({self._PYTHON312_URL!r}, "
                    "'/tmp/lion-py312.tar.gz')\n",
                    encoding="utf-8",
                )
                await self._upload_agent_owned_file(
                    environment,
                    fetch_script,
                    "/tmp/fetch_lion_py312.py",
                )
                await self.exec_as_root(
                    environment,
                    command=(
                        "rm -rf /opt/lion-py /tmp/lion-py312 && "
                        "python3 /tmp/fetch_lion_py312.py"
                    ),
                )
        await self.exec_as_root(
            environment,
            command=(
                "mkdir -p /tmp/lion-py312 && "
                "tar -xzf /tmp/lion-py312.tar.gz -C /tmp/lion-py312 && "
                "(test -x /tmp/lion-py312/python/bin/python3 && "
                "mv /tmp/lion-py312/python /opt/lion-py || tar -xzf "
                "/tmp/lion-py312.tar.gz -C /opt/lion-py --strip-components=1) && "
                "rm -rf /tmp/lion-py312 /tmp/lion-py312.tar.gz && "
                f"{self._REMOTE_PYTHON312}/bin/python3 --version"
            ),
        )

    @staticmethod
    def _cached_python312_tarball() -> Path | None:
        """返回评测主机上的固定版本 tarball 缓存路径(不存在则 None)。"""
        repository_root = Path(__file__).resolve().parents[2]
        return (
            repository_root
            / "benchmarks/agent_e2e/results/python312"
            / "install_only.tar.gz"
        )

    async def run(
        self,
        instruction: str,
        environment: Any,
        context: Any,
    ) -> None:
        """运行 worker，随后只下载受控结果文件，不下载原始 session/log。"""

        with tempfile.TemporaryDirectory(prefix="lion-harbor-request-") as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "manifest": json.loads(self._manifest_json),
                        "task": json.loads(self._task_json),
                        "attempt": self._attempt,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            await self._upload_agent_owned_file(
                environment,
                request_path,
                self._REMOTE_REQUEST,
            )
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"{self._REMOTE_PYTHON312}/bin/python3 -m "
                    "benchmarks.agent_e2e.worker_entrypoint"
                ),
                env={"PYTHONPATH": "/installed-agent"},
                timeout_sec=_timeout_seconds(self._manifest_json),
            )
        finally:
            result = await self._download_controlled(
                environment,
                "worker-result.json",
            )
            await self._download_controlled(environment, "trace.json")
            await self._download_controlled(environment, "analysis-trace.json")
            await self._download_controlled(environment, "lion.patch")
            if result is not None:
                _populate_context(context, result)

    async def _download_controlled(
        self,
        environment: Any,
        filename: str,
    ) -> Any | None:
        remote_path = f"{self._LOG_ROOT}/{filename}"
        if not await environment.is_file(remote_path):
            return None
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        local_path = self.logs_dir / filename
        await environment.download_file(remote_path, local_path)
        if filename != "worker-result.json":
            return None
        from .models import WorkerResult

        return WorkerResult.from_json(local_path.read_text(encoding="utf-8"))


def _json_text(value: str | Mapping[str, Any]) -> str:
    if isinstance(value, str):
        json.loads(value)
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _credential_env_names(manifest_json: str) -> tuple[str, ...]:
    payload = json.loads(manifest_json)
    profile = payload.get("profile")
    if not isinstance(profile, Mapping):
        return ()
    names = profile.get("credential_env_vars", ())
    return tuple(name for name in names if isinstance(name, str))


def _timeout_seconds(manifest_json: str) -> int:
    payload = json.loads(manifest_json)
    value = payload.get("timeout_seconds", 1)
    return max(1, int(float(value)))


def _populate_context(context: Any, result: Any) -> None:
    context.metadata = {"worker_status": result.status.value}
    if result.agent_run is None:
        return
    context.n_input_tokens = result.agent_run.input_tokens
    context.n_cache_tokens = result.agent_run.cache_read_tokens
    context.n_output_tokens = result.agent_run.output_tokens
    context.cost_usd = result.agent_run.cost_usd


__all__ = ["LionInstalledAgent"]
