"""桌面 sidecar 接口入口：API-only FastAPI + 动态 loopback 端口 + stdout ready 协议。"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import TextIO

_READY_TIMEOUT_SECONDS = 15.0


def format_ready_record(*, port: int, capability: str) -> str:
    """生成 ready 协议单行 JSON。"""
    return json.dumps(
        {"type": "ready", "version": 1, "port": port, "capability": capability},
        ensure_ascii=True,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lion-code-sidecar",
        description="Lion 桌面客户端的 Python sidecar 进程（由 Electron 托管）",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="工作区绝对路径（backend 会话与工具操作的根目录）",
    )
    return parser.parse_args(argv)


def build_session(workspace: Path):
    """在指定 workspace 下构造完整产品会话。"""
    os.chdir(workspace)
    from lion_code.application.session import LionCodingSession
    from lion_code.composition.full_product import build_full_coding_backend
    from lion_code.config import resolve_api_credentials

    creds = resolve_api_credentials(allow_placeholder=True)
    use_openai = bool(creds["use_openai"])
    backend = build_full_coding_backend(
        model=creds["model"] or "claude-opus-4-6",
        api_key=creds["api_key"],
        api_base=creds["api_base"] if use_openai else None,
        anthropic_base_url=creds["api_base"] if not use_openai else None,
    )
    return LionCodingSession(backend=backend, terminal_output=False)


def _apply_state_home() -> None:
    state_home = os.environ.get("LION_SIDECAR_STATE_HOME")
    if state_home:
        # 必须早于任何 server/composition/config import，避免模块常量绑定旧 HOME。
        os.environ["HOME"] = state_home
        os.environ["USERPROFILE"] = state_home


async def _serve_until_ready(
    server,
    sock: socket.socket,
    *,
    port: int,
    capability: str,
    protocol_out: TextIO | None = None,
    control_in: TextIO | None = None,
) -> None:
    """启动 uvicorn，端口绑定成功后输出 ready 记录并阻塞至服务退出。"""
    serve_task = asyncio.create_task(server.serve(sockets=[sock]))
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    try:
        while not server.started:
            if serve_task.done():
                await serve_task
                raise RuntimeError("sidecar 服务启动阶段意外退出")
            if time.monotonic() > deadline:
                raise TimeoutError("sidecar 就绪超时")
            await asyncio.sleep(0.05)
    except BaseException:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await serve_task
        raise

    out = sys.stdout if protocol_out is None else protocol_out
    out.write(format_ready_record(port=port, capability=capability) + "\n")
    out.flush()
    source = sys.stdin if control_in is None else control_in
    threading.Thread(
        target=_listen_for_shutdown,
        args=(source, server),
        daemon=True,
        name="lion-sidecar-control",
    ).start()
    await serve_task


def _listen_for_shutdown(source: TextIO, server) -> None:
    """父进程通过 stdin 单行命令请求优雅关闭；EOF 不改变服务状态。"""
    if source.readline().strip() == "shutdown":
        server.should_exit = True


def run(args: argparse.Namespace, protocol_out: TextIO | None = None) -> int:
    _apply_state_home()
    workspace = args.workspace
    if not workspace.is_dir():
        print(f"sidecar: 工作区不存在: {workspace}", file=sys.stderr)
        return 2

    from .server.app import create_app, generate_capability

    try:
        session = build_session(workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"sidecar: backend 构建失败: {exc}", file=sys.stderr)
        return 1

    capability = generate_capability()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(128)
        app = create_app(
            session=session,
            capability=capability,
            port=port,
            serve_static=False,
        )
    except Exception:
        sock.close()
        raise

    import uvicorn

    config = uvicorn.Config(app, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    try:
        asyncio.run(
            _serve_until_ready(
                server,
                sock,
                port=port,
                capability=capability,
                protocol_out=protocol_out,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"sidecar: 服务异常退出: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
