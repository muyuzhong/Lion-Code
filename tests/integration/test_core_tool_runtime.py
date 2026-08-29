"""Core + Lion ToolRuntime integration through the tool adapter (FakeProvider).

These tests drive the real ``ToolRuntime`` (with its middleware chain) from the
portable core via ``adapt_active_tools``, using a scripted ``FakeProvider`` so no
real OpenAI/Anthropic call is made. They prove the full closed loop:
provider tool call -> AgentHarness -> adapter -> ToolRuntime -> middleware ->
LionTool -> ToolResultMessage -> provider final response.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from core.fakes import FakeProvider

from lion_code.adapters import adapt_active_tools
from lion_code.core import (
    AgentHarness,
    AgentHarnessConfig,
    AssistantMessage,
    TextContent,
    ToolCall,
)
from lion_code.core.cancellation import CancellationToken
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.runtime.session_identity import SessionIdentityState
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
        registry=registry,
        permission=PermissionController(PermissionState("default")),
        read_file_state={},
    )

def _echo_lion_tool() -> LionTool:
    async def execute(_ctx, _id, arguments, _on_update):
        return ToolResult(content=f"echo:{arguments.get('msg', '')}")

    return LionTool(
        name="echo",
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

class _DenyMiddleware:
    """Simulates a permission/hook denial: returns a structured error, never raises."""

    phase = "pre"

    async def handle(self, *, tool, context, tool_call_id, arguments, call_next, **_):
        return ToolResult(content="Action denied by policy", is_error=True)

class TestCoreToolRuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_closed_loop_through_real_tool_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        runtime = ToolRuntime(registry, _context(registry))

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="echo", arguments={"msg": "hi"})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="done")],
                        stop_reason="stop",
                    ),
                ),
            ]
        )

        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[],
                get_tools=lambda: adapt_active_tools(runtime),
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        messages = harness.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        tool_result = messages[2]
        self.assertFalse(tool_result.is_error)
        self.assertEqual(tool_result.text, "echo:hi")
        self.assertEqual(messages[3].text, "done")
        # get_tools fired once per model request (2 turns), exposing the real
        # Lion tool to the provider each time.
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(provider.received_tools[0], ["echo"])

    async def test_permission_denial_flows_as_structured_error(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        runtime = ToolRuntime(registry, _context(registry), [_DenyMiddleware()])

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="echo", arguments={"msg": "hi"})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="recovered")],
                        stop_reason="stop",
                    ),
                ),
            ]
        )

        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[],
                get_tools=lambda: adapt_active_tools(runtime),
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        tool_result = harness.messages[2]
        self.assertTrue(tool_result.is_error)
        self.assertIn("denied", tool_result.text.lower())

