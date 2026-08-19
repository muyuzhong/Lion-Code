"""CodingSessionBackendAdapter：组合实现 CodingSessionBackend 的产品适配器。"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from lion_code.adapters.coding_session_backend import (
    CodingSessionBackendAdapter,
    build_full_coding_backend,
)
from lion_code.application.ports import CodingSessionBackend
from lion_code.meta_agent import MetaAgent
from lion_code.session_runtime import SessionRepository


def _backend(tmp_path: Path, **kwargs) -> CodingSessionBackendAdapter:
    with patch(
        "lion_code.composition.agent_builder.create_provider"
    ) as create:
        create.return_value = _FakeProvider()
        backend = build_full_coding_backend(
            api_key="test-key",
            terminal_output=False,
            session_repository=SessionRepository(session_dir=tmp_path / "sessions"),
            **kwargs,
        )
    return backend


class _FakeProvider:
    async def aclose(self) -> None: ...


class TestComposition(unittest.TestCase):
    def test_adapter_implements_protocol_structurally(self):
        with patch(
            "lion_code.composition.agent_builder.create_provider", return_value=_FakeProvider()
        ):
            backend = build_full_coding_backend(
                api_key="test-key", terminal_output=False
            )
        self.assertIsInstance(backend, CodingSessionBackend)

    def test_adapter_does_not_inherit_meta_agent(self):
        self.assertFalse(issubclass(CodingSessionBackendAdapter, MetaAgent))
        self.assertNotIn(MetaAgent, CodingSessionBackendAdapter.__mro__)


class TestLegacySessionMigration(unittest.IsolatedAsyncioTestCase):
    async def test_list_sessions_merges_legacy_json(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = SessionRepository(session_dir=tmp_path / "sessions")
            repo.session_dir.mkdir(parents=True)
            # 旧 JSON session：迁移前应出现在枚举结果中。
            legacy = {
                "id": "legacy-1",
                "metadata": {"model": "m", "cwd": tmp},
                "anthropicMessages": [],
            }
            (repo.session_dir / "legacy-1.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
            backend = _backend(tmp_path)
            backend._session_repository = repo
            sessions = await backend.list_sessions()
            self.assertEqual([item["id"] for item in sessions], ["legacy-1"])

    async def test_resume_migrates_legacy_then_restores(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = SessionRepository(session_dir=tmp_path / "sessions")
            repo.session_dir.mkdir(parents=True)
            legacy = {
                "id": "legacy-2",
                "metadata": {"model": "m", "cwd": tmp},
                "anthropicMessages": [],
            }
            (repo.session_dir / "legacy-2.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
            backend = _backend(tmp_path)
            backend._session_repository = repo
            restored = await backend.resume("legacy-2")
            self.assertTrue(restored)
            # 迁移后旧 JSON 保留、新 JSONL 存在且不再重复枚举。
            self.assertTrue((repo.session_dir / "legacy-2.json").exists())
            self.assertTrue((repo.session_dir / "legacy-2.jsonl").exists())
            sessions = await backend.list_sessions()
            self.assertEqual(len(sessions), 1)


class TestTerminalAndCallbacks(unittest.IsolatedAsyncioTestCase):
    def test_set_terminal_output_flips_three_switches(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            backend = _backend(Path(tmp))
            backend.set_terminal_output(True)
            self.assertTrue(backend._confirmation.terminal_output)
            self.assertTrue(backend._status_sink.terminal_output)

    def test_notice_and_confirm_routing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            backend = _backend(Path(tmp))
            seen: list[str] = []
            backend.set_notice_fn(lambda msg, role="info": seen.append(msg))
            backend.show_cost()
            self.assertEqual(len(seen), 1)
            self.assertIn("Tokens:", seen[0])

            async def confirm(_: str) -> bool:
                return True

            backend.set_confirm_fn(confirm)
            self.assertIs(backend._confirmation.confirm_fn, confirm)

    def test_toggle_plan_mode_delegates_to_plan_runtime(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            backend = _backend(Path(tmp))
            self.assertEqual(backend.toggle_plan_mode(), "plan")


if __name__ == "__main__":
    unittest.main()
