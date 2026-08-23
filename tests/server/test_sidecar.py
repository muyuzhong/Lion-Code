"""sidecar 进程入口与 API-only app 构造的契约测试。"""

from __future__ import annotations

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lion_code.application.session import LionCodingSession
from lion_code.server.app import create_app
from lion_code.sidecar import format_ready_record

try:
    from application.fakes import FakeCodingSessionBackend
except ModuleNotFoundError:
    from tests.application.fakes import FakeCodingSessionBackend

_CAPABILITY = "A" * 43
_DESKTOP_ORIGIN = "lion://app"


class _StdoutHarness:
    """后台线程逐行收集子进程 stdout，规避 Windows 管道的非阻塞限制。"""

    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._pump, daemon=True)

    def start(self) -> None:
        self._reader.start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for raw in iter(self.process.stdout.readline, b""):
            with self._lock:
                self._lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def wait_ready(self, timeout_seconds: float) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            lines = self.lines()
            if lines:
                return json.loads(lines[0])
            if self.process.poll() is not None:
                stderr_tail = b""
                if self.process.stderr is not None:
                    # 进程已退出，可安全读取全部 stderr。
                    stderr_tail = self.process.stderr.read()[-2000:]
                raise AssertionError(
                    "sidecar 提前退出: " + stderr_tail.decode("utf-8", errors="replace")
                )
            time.sleep(0.2)
        raise AssertionError("等待 ready 记录超时")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


def _build_client(session: LionCodingSession, *, origin: str) -> TestClient:
    return TestClient(
        create_app(session, capability=_CAPABILITY, serve_static=False),
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {_CAPABILITY}", "Origin": origin},
    )


def _build_test_session() -> LionCodingSession:
    backend = FakeCodingSessionBackend(cwd=Path("/workspace"), model="gpt-4o")
    return LionCodingSession(backend=backend)


class TestFormatReadyRecord:
    def test_ready_record_is_single_line_strict_json(self):
        line = format_ready_record(port=49152, capability=_CAPABILITY)

        assert "\n" not in line
        record = json.loads(line)
        assert record == {
            "type": "ready",
            "version": 1,
            "port": 49152,
            "capability": _CAPABILITY,
        }

    def test_shutdown_control_sets_server_exit_flag(self):
        from lion_code.sidecar import _listen_for_shutdown

        server = type("Server", (), {"should_exit": False})()
        _listen_for_shutdown(io.StringIO("shutdown\n"), server)

        assert server.should_exit is True


class TestParseArgs:
    def test_state_home_applies_before_config_import(self, tmp_path):
        state_home = tmp_path / "state"
        repo_root = Path(__file__).resolve().parents[2]
        probe = (
            "from lion_code.sidecar import _apply_state_home\n"
            "_apply_state_home()\n"
            "from lion_code.config import CONFIG_PATH\n"
            "print(CONFIG_PATH)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=repo_root,
            env={**os.environ, "LION_SIDECAR_STATE_HOME": str(state_home)},
            capture_output=True,
            text=True,
            check=True,
        )

        assert Path(result.stdout.strip()) == state_home / ".lion-code" / "config.json"

    def test_workspace_is_required(self):
        from lion_code.sidecar import _parse_args

        with pytest.raises(SystemExit) as excinfo:
            _parse_args([])

        assert excinfo.value.code == 2

    def test_missing_workspace_directory_fails_fast(self, tmp_path, capsys):
        from lion_code.sidecar import run

        args = argparse.Namespace(workspace=tmp_path / "missing")
        exit_code = run(args, protocol_out=io.StringIO())

        assert exit_code == 2
        assert "工作区不存在" in capsys.readouterr().err


class TestApiOnlyApp:
    def test_api_only_does_not_mount_static_frontend(self):
        client = _build_client(_build_test_session(), origin=_DESKTOP_ORIGIN)

        response = client.get("/")

        assert response.status_code == 404

    def test_health_stays_public_without_capability(self):
        client = TestClient(
            create_app(
                _build_test_session(), capability=_CAPABILITY, serve_static=False
            ),
            base_url="http://127.0.0.1:8000",
        )

        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_desktop_origin_accepted_for_api(self):
        client = _build_client(_build_test_session(), origin=_DESKTOP_ORIGIN)

        response = client.get("/api/status")

        assert response.status_code == 200

    def test_desktop_origin_accepted_for_websocket(self):
        client = _build_client(_build_test_session(), origin=_DESKTOP_ORIGIN)

        with client.websocket_connect(
            "ws://127.0.0.1:8000/ws/chat",
            subprotocols=["lion-code", f"lion-code-capability.{_CAPABILITY}"],
            headers={"Origin": _DESKTOP_ORIGIN},
        ) as websocket:
            assert websocket.accepted_subprotocol == "lion-code"
            websocket.send_text(json.dumps({"type": "ping"}))
            # 未注册消息类型由 bridge 忽略；连接保持打开即通过。

    def test_unknown_origin_rejected_for_api(self):
        client = _build_client(_build_test_session(), origin="https://attacker.example")

        response = client.get("/api/status")

        assert response.status_code == 403


class TestSidecarProcess:
    """真实子进程契约：ready 记录 schema、动态端口、health 可达、stderr 分流。"""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    @pytest.fixture
    def sidecar(self, workspace: Path, tmp_path: Path):
        repo_root = Path(__file__).resolve().parents[2]
        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            # 隔离用户级 ~/.lion-code（凭证与 session 存储）；必须位于 workspace
            # 之外，否则工具快照存储路径校验会拒绝启动。
            "HOME": str(tmp_path / "home"),
            "USERPROFILE": str(tmp_path / "home"),
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lion_code.sidecar",
                "--workspace",
                str(workspace),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            cwd=str(repo_root),
            env=env,
        )
        harness = _StdoutHarness(process)
        harness.start()
        try:
            yield harness
        finally:
            harness.close()

    def test_ready_record_and_loopback_health(self, sidecar):
        record = sidecar.wait_ready(timeout_seconds=60)

        assert set(record) == {"type", "version", "port", "capability"}
        assert record["type"] == "ready"
        assert record["version"] == 1
        assert isinstance(record["port"], int)
        assert 0 < record["port"] < 65536
        capability = record["capability"]
        assert isinstance(capability, str) and len(capability) >= 32
        assert all(c.isalnum() or c in "-_" for c in capability)

        # 端口必须是 OS 分配的动态端口（bind 0），且只绑定 loopback。
        with socket.socket() as probe:
            probe.connect(("127.0.0.1", record["port"]))

        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{record['port']}/api/health", timeout=10
        ) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"status": "ok"}

        # capability 只经 stdout 管道交付，绝不进入 argv。
        assert capability not in json.dumps(sidecar.process.args)

    def test_stdout_carries_only_ready_record(self, sidecar):
        sidecar.wait_ready(timeout_seconds=60)

        # ready 之后 stdout 不再有输出（含访问日志）；诊断全部走 stderr。
        time.sleep(1.0)
        assert len(sidecar.lines()) == 1

    def test_shutdown_command_exits_cleanly(self, sidecar):
        sidecar.wait_ready(timeout_seconds=60)
        assert sidecar.process.stdin is not None

        sidecar.process.stdin.write(b"shutdown\n")
        sidecar.process.stdin.flush()

        assert sidecar.process.wait(timeout=10) == 0
