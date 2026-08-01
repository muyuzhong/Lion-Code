"""McpConnection / McpManager 容错分支的单测。

覆盖 mcp_client.py 里此前无测试覆盖的两条失败容错路径(m-007):

1. ``McpManager.load_and_connect`` 的 ``except`` 分支--单个 Server 子进程启动失败时,
   跳过该 Server 而不中断其他 Server(连接失败隔离)。
2. ``McpConnection._read_loop`` 的 ``if not line: break`` 分支--Server stdout 关闭
   (EOF)时读循环干净退出,不挂起、不残留任务。

这两条都是容错路径而非「重连」逻辑:代码库不存在自动重连,只有失败隔离与 EOF 退出。
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from lion_code.mcp_client import McpConnection, McpManager


class TestMcpConnectionReadLoop(unittest.IsolatedAsyncioTestCase):
    async def test_read_loop_exits_cleanly_on_stdout_eof(self) -> None:
        """Server stdout 关闭(空 readline)时,读循环必须立即退出且不挂起。"""
        conn = McpConnection("srv", "cmd")
        fake_stdout = AsyncMock()
        fake_stdout.readline = AsyncMock(return_value=b"")
        conn._process = SimpleNamespace(stdout=fake_stdout, stdin=SimpleNamespace())

        # 若 EOF 分支未正确 break,wait_for 会超时失败。
        await asyncio.wait_for(conn._read_loop(), timeout=1.0)

        fake_stdout.readline.assert_awaited()

    async def test_read_loop_dispatches_response_then_exits_on_eof(self) -> None:
        """匹配的 JSON-RPC 响应应唤醒对应 pending future,随后 EOF 退出循环。"""
        conn = McpConnection("srv", "cmd")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        conn._pending[7] = future

        fake_stdout = AsyncMock()
        fake_stdout.readline = AsyncMock(
            side_effect=[
                b'{"id": 7, "result": {"ok": true}}\n',
                b"",
            ]
        )
        conn._process = SimpleNamespace(stdout=fake_stdout, stdin=SimpleNamespace())

        await asyncio.wait_for(conn._read_loop(), timeout=1.0)

        self.assertTrue(future.done())
        self.assertEqual(future.result(), {"ok": True})
        self.assertNotIn(7, conn._pending)

    async def test_read_loop_routes_error_response_as_exception(self) -> None:
        """错误响应应把异常塞进对应 pending future。"""
        conn = McpConnection("srv", "cmd")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        conn._pending[3] = future

        fake_stdout = AsyncMock()
        fake_stdout.readline = AsyncMock(
            side_effect=[
                b'{"id": 3, "error": {"code": -32000, "message": "boom"}}\n',
                b"",
            ]
        )
        conn._process = SimpleNamespace(stdout=fake_stdout, stdin=SimpleNamespace())

        await asyncio.wait_for(conn._read_loop(), timeout=1.0)

        self.assertTrue(future.done())
        with self.assertRaises(RuntimeError):
            future.result()


class TestMcpManagerFailureIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_load_and_connect_skips_server_that_fails_to_start(self) -> None:
        """子进程命令不存在时,该 Server 被跳过,manager 不抛错、不残留连接。"""
        manager = McpManager()
        manager._load_configs = lambda: {
            "bad": {"command": "nonexistent-command-xyz-12345"},
        }

        await manager.load_and_connect()

        self.assertEqual(manager._connections, {})
        self.assertEqual(manager._tools, [])
        # 连接失败已走 except 分支并 close,_connected 仍置位(单次初始化语义)。
        self.assertTrue(manager._connected)

    async def test_load_and_connect_is_idempotent(self) -> None:
        """已初始化后再次调用不得重新读配置或建连。"""
        manager = McpManager()
        call_count = 0

        def _configs() -> dict:
            nonlocal call_count
            call_count += 1
            return {}

        manager._load_configs = _configs
        await manager.load_and_connect()
        await manager.load_and_connect()

        # _connected 置位后第二次应直接返回,_load_configs 只被调用一次。
        self.assertEqual(call_count, 1)


if __name__ == "__main__":
    unittest.main()
