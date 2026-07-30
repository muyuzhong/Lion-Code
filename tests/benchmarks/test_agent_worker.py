"""评测 Agent worker 的 MCP 与会话隔离回归测试。"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from benchmarks.agent_e2e.agent_worker import run_agent_worker
from benchmarks.agent_e2e.backend import AgentExecutionRequest
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.models import (
    Catalog,
    ExperimentManifest,
    ExperimentProfile,
    TaskSpec,
    TaskSplit,
    WorkerStatus,
)
from lion_code.agent import Agent
from lion_code.core import AssistantMessage, TextContent, Usage
from lion_code.core.provider_events import AssistantDoneEvent


class _SingleEventProvider:
    """仅供本文件驱动真实 Agent 的最小流式 provider。"""

    def __init__(self, event: AssistantDoneEvent) -> None:
        self._event = event

    async def aclose(self) -> None:
        return None

    def stream_response(self, **_kwargs):
        return self._stream()

    async def _stream(self):
        yield self._event


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="worker-task",
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="修复公开问题。",
        verifier_identity="hidden-v1",
        gold_evidence_hash="a" * 64,
        difficulty=1,
    )


def _manifest(task: TaskSpec) -> ExperimentManifest:
    catalog = Catalog(catalog_id="worker", catalog_version="v1", tasks=(task,))
    profile = ExperimentProfile(
        profile_id="worker-fake",
        model="fake-model",
        provider="fake",
        prompt_version="prompt-v1",
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=0,
        agent_code_sha="abcdef0",
    )
    return ExperimentManifest(
        run_id="worker-run",
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha="1234567",
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="offline-test",
    )


def _completed_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake-model",
            content=[TextContent(text="完成")],
            stop_reason="stop",
            usage=Usage(input=3, output=2),
        ),
    )


class TestAgentWorker(unittest.IsolatedAsyncioTestCase):
    async def test_worker_disables_mcp_and_keeps_session_outside_workspace(self) -> None:
        task = _task()
        manifest = _manifest(task)
        created_agents: list[Agent] = []
        discoveries: list[AsyncMock] = []

        def factory(**kwargs) -> Agent:
            agent = Agent(api_key="test-key", **kwargs)
            discovery = AsyncMock(return_value=[])
            agent._mcp_manager.discover_tools = discovery
            created_agents.append(agent)
            discoveries.append(discovery)
            return agent

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            agent_workspace = root / "agent-workspace"
            agent_workspace.mkdir()
            session_root = root / "evaluation-sessions"
            request = AgentExecutionRequest(
                manifest=manifest,
                task=task,
                attempt=1,
                agent_workspace=agent_workspace,
                session_root=session_root,
                mcp_enabled=False,
            )
            with patch(
                "lion_code.agent.create_provider",
                return_value=_SingleEventProvider(_completed_event()),
            ):
                result = await run_agent_worker(request, agent_factory=factory)

            self.assertEqual(result.status, WorkerStatus.COMPLETED)
            self.assertIsNotNone(result.agent_run)
            self.assertEqual(
                result.agent_run.final_text_digest,
                hashlib.sha256("完成".encode("utf-8")).hexdigest(),
            )
            self.assertEqual(len(created_agents), 1)
            self.assertFalse(created_agents[0].mcp_enabled)
            discoveries[0].assert_not_awaited()
            self.assertTrue(any(session_root.rglob("*.jsonl")))
            self.assertFalse(any(agent_workspace.rglob("*.jsonl")))

    async def test_worker_rejects_any_enabled_mcp_request(self) -> None:
        task = _task()
        manifest = _manifest(task)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "agent-workspace"
            workspace.mkdir()
            request = AgentExecutionRequest(
                manifest=manifest,
                task=task,
                attempt=1,
                agent_workspace=workspace,
                session_root=root / "evaluation-sessions",
                mcp_enabled=True,
            )

            with self.assertRaisesRegex(ValueError, "mcp_enabled=False"):
                await run_agent_worker(request)


if __name__ == "__main__":
    unittest.main()
