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
from lion_code.tooling.middleware import WorkspaceSnapshotMiddleware
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.snapshot import WorkspaceSnapshot
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

    async def test_rollback_notice_reaches_next_model_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as storage_directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            state = root / "state.txt"
            state.write_text("before", encoding="utf-8")
            snapshot = WorkspaceSnapshot(root, Path(storage_directory))
            target_snapshot_id = snapshot.create()
            state.write_text("after", encoding="utf-8")

            registry = ToolRegistry()
            runtime_holder: dict[str, ToolRuntime] = {}

            async def rollback_tool(_context, _id, _arguments, _on_update):
                return runtime_holder["runtime"].rollback(
                    target_snapshot_id,
                    "撤销错误写入",
                )

            registry.register(
                LionTool(
                    name="rollback_workspace",
                    label="Rollback workspace",
                    description="restore a workspace snapshot",
                    parameters={"type": "object", "properties": {}},
                    execute_fn=rollback_tool,
                    capabilities=ToolCapabilities(read_only=True),
                )
            )
            runtime_context = _context(registry)
            runtime_context.workspace_snapshot = snapshot
            runtime = ToolRuntime(
                registry,
                runtime_context,
                [WorkspaceSnapshotMiddleware(snapshot)],
            )
            runtime_holder["runtime"] = runtime

            provider = FakeProvider(
                [
                    AssistantDoneEvent(
                        reason="toolUse",
                        message=AssistantMessage(
                            model="fake",
                            content=[
                                ToolCall(
                                    id="rollback-1",
                                    name="rollback_workspace",
                                    arguments={},
                                )
                            ],
                            stop_reason="toolUse",
                        ),
                    ),
                    AssistantDoneEvent(
                        reason="stop",
                        message=AssistantMessage(
                            model="fake",
                            content=[TextContent(text="re-evaluated")],
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

            async for _ in harness.prompt("rollback the failed operation"):
                pass

            tool_result = harness.messages[2]
            self.assertEqual(
                tool_result.text,
                "以下操作结果已被撤销，请基于当前 workspace 重新判断",
            )
            self.assertEqual(harness.messages[3].text, "re-evaluated")
            self.assertEqual(state.read_text(encoding="utf-8"), "before")


if __name__ == "__main__":
    unittest.main(verbosity=2)
