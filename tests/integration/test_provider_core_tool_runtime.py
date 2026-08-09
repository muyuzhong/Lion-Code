"""真实 provider 闭环集成测试：OpenAICompatibleProvider -> Core -> ToolRuntime。

不同于 ``test_core_tool_runtime`` 使用脚本化 ``FakeProvider``，这里用真实的
``OpenAICompatibleProvider`` 配合 ``httpx.MockTransport`` 注入伪造 SSE，验证
完整闭环：provider 工具调用 -> AgentHarness -> adapt_active_tools ->
ToolRuntime -> LionTool -> ToolResultMessage -> provider 第二次请求 ->
最终 AssistantMessage。重点校验第二次 HTTP 请求的载荷中带回了
user / assistant(tool_calls) / tool 三段对话。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import httpx

from lion_code.adapters import adapt_active_tools
from lion_code.core import AgentHarness, AgentHarnessConfig
from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.providers.config import OpenAICompatibleConfig
from lion_code.providers.openai_compatible import OpenAICompatibleProvider
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


class _Controller:
    pass


def _context(registry: ToolRegistry) -> ToolContext:
    return ToolContext(
        session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        controller=_Controller(),
        registry=registry,
        permission=PermissionController(PermissionState("default")),
        plan_file_path=None,
        read_file_state={},
    )


def _echo_lion_tool() -> LionTool:
    async def execute(_ctx, _id, arguments, _on_update):
        return ToolResult(content=f"echo:{arguments.get('msg', '')}")

    return LionTool(
        name="echo",
        label="Echo",
        description="echo the msg argument",
        parameters={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True, concurrency_safe=True),
        execution_mode="parallel",
    )


def _sse(*items: Any) -> bytes:
    parts: list[str] = []
    for item in items:
        payload = item if isinstance(item, str) else json.dumps(item)
        parts.append(f"data: {payload}\n\n")
    return "".join(parts).encode()


def _chat_delta(delta: dict[str, Any], *, finish_reason: str | None = None) -> dict[str, Any]:
    choice: dict[str, Any] = {"delta": delta}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice]}


class TestProviderCoreToolRuntimeLoop(unittest.IsolatedAsyncioTestCase):
    async def test_closed_loop_carries_tool_transcript_into_second_request(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        runtime = ToolRuntime(registry, _context(registry))

        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                # 第一次请求：模型要求调用 echo({"msg": "hi"})。
                return httpx.Response(
                    200,
                    content=_sse(
                        _chat_delta(
                            {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "function": {
                                            "name": "echo",
                                            "arguments": json.dumps({"msg": "hi"}),
                                        },
                                    }
                                ]
                            }
                        ),
                        _chat_delta({}, finish_reason="tool_calls"),
                        "[DONE]",
                    ),
                )
            # 第二次请求：模型给出最终文本。
            return httpx.Response(
                200,
                content=_sse(
                    _chat_delta({"content": "done"}),
                    _chat_delta({}, finish_reason="stop"),
                    "[DONE]",
                ),
            )

        config = OpenAICompatibleConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            max_retries=2,
            max_retry_delay_seconds=0.0,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(config, client=client)
            harness = AgentHarness(
                AgentHarnessConfig(
                    provider=provider,
                    model="gpt-4",
                    system="s",
                    tools=[],
                    get_tools=lambda: adapt_active_tools(runtime),
                )
            )

            async for _ in harness.prompt("hello"):
                pass

        # 闭环消息序列：user -> assistant(tool call) -> toolResult -> assistant。
        messages = harness.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[1].tool_calls[0].name, "echo")
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[3].text, "done")

        # 两次模型请求，且第二次请求带回完整工具对话。
        self.assertEqual(len(requests), 2)
        second_body = json.loads(requests[1].content)
        msgs = second_body["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": "s"})
        self.assertEqual(msgs[1], {"role": "user", "content": "hello"})
        self.assertEqual(msgs[2]["role"], "assistant")
        self.assertEqual(msgs[2]["content"], "")
        tool_call_payload = msgs[2]["tool_calls"][0]
        self.assertEqual(tool_call_payload["id"], "call-1")
        self.assertEqual(tool_call_payload["type"], "function")
        self.assertEqual(tool_call_payload["function"]["name"], "echo")
        self.assertEqual(json.loads(tool_call_payload["function"]["arguments"]), {"msg": "hi"})
        self.assertEqual(
            msgs[3],
            {"role": "tool", "tool_call_id": "call-1", "name": "echo", "content": "echo:hi"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
