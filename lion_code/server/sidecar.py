"""桌面 sidecar 进程入口：API-only FastAPI + 动态 loopback 端口 + stdout ready 协议。

Electron Main 是本进程的唯一父进程与协议对端：

- stdout 全程只承载 ready JSON 单行记录；进程内一切其他输出在 fd 级别重定向到
  stderr，杜绝第三方库污染协议通道。
- 端口由 OS 分配（bind 0，父子全程持有 socket 防抢占），capability 仅经 stdout
  管道交付，不进入 argv、URL 或磁盘。
- workspace 通过唯一启动参数传入；backend workspace 取进程 cwd
  （``agent_builder`` 的 ``Path.cwd()``），因此先 chdir 再构造产品。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import TextIO, TypedDict

_READY_TIMEOUT_SECONDS = 15.0
_PLACEHOLDER_OPENAI_BASE_URL = "https://api.openai.com/v1"


class _ProviderStartupConfig(TypedDict):
    api_key: str | None
    api_base: str | None
    use_openai: bool
    model: str | None


def _hijack_stdout() -> TextIO:
    """把 fd 1 及 Python 层 stdout 全部指向 stderr，返回协议专用输出流。"""
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(protocol_fd, "w", encoding="utf-8")


def format_ready_record(*, port: int, capability: str) -> str:
    """生成 ready 协议单行 JSON；字段集合是 Electron Main 严格解析的契约。"""
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


def _resolve_provider_config() -> _ProviderStartupConfig:
    """镜像 Web 启动的凭证回退：环境变量 > 已保存配置 > 占位端点。

    无凭证启动是合法状态：首跑配置由桌面 UI 经 /api/config/provider 完成，
    这里只提供 OpenAI 兼容占位端点避免 Provider 构造失败。
    """
    from lion_code.config import load_api_config

    api_key: str | None = None
    api_base: str | None = None
    use_openai = False

    env = os.environ
    if env.get("OPENAI_API_KEY") and env.get("OPENAI_BASE_URL"):
        api_key = env["OPENAI_API_KEY"]
        api_base = env["OPENAI_BASE_URL"]
        use_openai = True
    elif env.get("ANTHROPIC_API_KEY"):
        api_key = env["ANTHROPIC_API_KEY"]
        api_base = env.get("ANTHROPIC_BASE_URL") or None
    elif env.get("OPENAI_API_KEY"):
        api_key = env["OPENAI_API_KEY"]
        api_base = env.get("OPENAI_BASE_URL") or None
        use_openai = True

    model: str | None = None
    if api_key is None:
        saved = load_api_config()
        if saved.get("api_key"):
            api_key = saved["api_key"]
            use_openai = saved.get("provider") == "openai"
            api_base = saved.get("base_url") or None
            model = saved.get("model") or None

    if api_key is None and not use_openai:
        use_openai = True
        api_base = api_base or _PLACEHOLDER_OPENAI_BASE_URL

    return {
        "api_key": api_key,
        "api_base": api_base,
        "use_openai": use_openai,
        "model": model,
    }


def build_session(workspace: Path):
    """在指定 workspace 下构造完整产品会话（与 Web 模式同一 Composition Root）。"""
    os.chdir(workspace)
    from lion_code.application.session import LionCodingSession
    from lion_code.composition.full_product import build_full_coding_backend

    provider = _resolve_provider_config()
    use_openai = bool(provider["use_openai"])
    backend = build_full_coding_backend(
        model=provider["model"] or "claude-opus-4-6",
        api_key=provider["api_key"],
        api_base=provider["api_base"] if use_openai else None,
        anthropic_base_url=provider["api_base"] if not use_openai else None,
    )
    return LionCodingSession(backend=backend, terminal_output=False)


async def _serve_until_ready(
    server,
    sock: socket.socket,
    protocol_out: TextIO,
    *,
    port: int,
    capability: str,
) -> None:
    """启动 uvicorn，端口绑定成功后输出 ready 记录并阻塞至服务退出。

    socket 所有权在本函数移交 uvicorn（其关闭时回收）；启动失败路径由调用方
    负责关闭，保证端口不泄漏。
    """
    serve_task = asyncio.create_task(server.serve(sockets=[sock]))
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    try:
        while not server.started:
            if serve_task.done():
                await serve_task  # 重抛底层异常
                raise RuntimeError("sidecar 服务启动阶段意外退出")
            if time.monotonic() > deadline:
                raise TimeoutError("sidecar 就绪超时")
            await asyncio.sleep(0.05)
    except BaseException:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await serve_task
        raise

    protocol_out.write(format_ready_record(port=port, capability=capability) + "\n")
    protocol_out.flush()
    await serve_task


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：先隔离 stdout 协议通道，再进入可编程测试的 run()。"""
    protocol_out = _hijack_stdout()
    return run(_parse_args(argv), protocol_out)


def run(args: argparse.Namespace, protocol_out: TextIO) -> int:
    workspace = args.workspace
    if not workspace.is_dir():
        print(f"sidecar: 工作区不存在: {workspace}", file=sys.stderr)
        return 2

    from .app import create_app, generate_capability

    try:
        session = build_session(workspace)
    except Exception as exc:  # noqa: BLE001 入口边界：诊断信息全部进 stderr
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

    config = uvicorn.Config(
        app,
        log_level="info",
        access_log=False,
        # uvicorn 默认把 access log 写 stdout；fd 级重定向已兜底，这里显式关闭。
    )
    server = uvicorn.Server(config)
    try:
        asyncio.run(
            _serve_until_ready(
                server, sock, protocol_out, port=port, capability=capability
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"sidecar: 服务异常退出: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
