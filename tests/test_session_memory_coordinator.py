from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from lion_code.agent import Agent
from lion_code.memory_runtime import ProviderTextQueryService
from lion_code.project_identity import resolve_project_identity
from lion_code.session_memory import SessionMemory, SessionMemoryRepository
from lion_code.session_memory_coordinator import SessionMemoryCoordinator


class TestSessionMemoryCoordinator(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        identity = resolve_project_identity()
        self._repository = SessionMemoryRepository(
            identity,
            storage_dir=Path(self._temp_dir.name) / "session-memory",
        )
        self._agent = Agent(
            api_key="test-key",
            session_memory_repository=self._repository,
            mcp_enabled=False,
            terminal_output=False,
        )

    async def asyncTearDown(self) -> None:
        await self._agent.close()
        self._temp_dir.cleanup()

    async def test_agent_owns_memory_state_through_coordinator(self) -> None:
        self.assertIsInstance(
            self._agent._session_memory_coord,
            SessionMemoryCoordinator,
        )
        self.assertIs(
            self._agent._memory_coordinator,
            self._agent._session_memory_coord.memory_coordinator,
        )
        query_service = self._agent._memory_coordinator._query_service
        self.assertIsInstance(query_service, ProviderTextQueryService)
        self.assertIs(query_service._provider, self._agent.core_runtime.provider)

    async def test_agent_private_state_setters_preserve_test_and_runtime_seams(
        self,
    ) -> None:
        memory = SessionMemory(
            project_root=str(self._repository.identity.root),
            active_task="验证协调器",
        )
        self._agent._session_memory = self._repository.save(memory)
        self.assertEqual(self._agent.session_memory.active_task, "验证协调器")

        original = self._agent._memory_coordinator
        replacement = Mock()
        self._agent._memory_coordinator = replacement
        self.assertIs(self._agent._memory_coordinator, replacement)
        self._agent._memory_coordinator = original

    async def test_public_commands_remain_thin_coordinator_delegates(self) -> None:
        self._agent._session_memory_coord.show_active_task = Mock(
            return_value="# Current Task"
        )
        self.assertEqual(self._agent.show_active_task(), "# Current Task")
        self._agent._session_memory_coord.show_active_task.assert_called_once_with()

    async def test_dream_public_entry_delegates_to_coordinator(self) -> None:
        agent = Agent.__new__(Agent)
        coordinator = Mock()
        coordinator.dream = AsyncMock(return_value="Dream 完成")
        agent._session_memory_coord = coordinator

        self.assertEqual(await agent.dream(), "Dream 完成")
        coordinator.dream.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
