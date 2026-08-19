from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lion_code.capabilities.plan import PlanPromptLayer, PlanSessionParticipant
from lion_code.capabilities.plan.runtime import PlanRuntime, PlanState


class _Host:
    def __init__(self) -> None:
        self.session_id = "session-one"
        self.notices: list[str] = []

    def _emit_notice(self, message: str, *, role: str = "info") -> None:
        self.notices.append(f"{role}:{message}")


def _runtime() -> tuple[PlanRuntime, _Host]:
    host = _Host()
    runtime = PlanRuntime(host, PlanState())
    return runtime, host


class TestPlanRuntime(unittest.IsolatedAsyncioTestCase):
    def test_initial_state_is_inactive(self) -> None:
        runtime, _host = _runtime()

        self.assertFalse(runtime.is_active)
        self.assertIsNone(runtime.file_path)

    def test_enter_path_error_does_not_publish_partial_state(self) -> None:
        runtime, _host = _runtime()

        with (
            patch.object(
                runtime,
                "_generate_file_path",
                side_effect=OSError("path unavailable"),
            ),
            self.assertRaisesRegex(OSError, "path unavailable"),
        ):
            runtime.enter()

        self.assertFalse(runtime.is_active)
        self.assertIsNone(runtime.file_path)

    def test_toggle_activates_and_deactivates_without_touching_permission(
        self,
    ) -> None:
        runtime, host = _runtime()
        plan_path = Path("plan.md")

        with patch.object(runtime, "_generate_file_path", return_value=plan_path):
            self.assertEqual(runtime.toggle(), "plan")
            self.assertTrue(runtime.is_active)
            self.assertEqual(runtime.file_path, plan_path)
            self.assertIn("Entered plan mode", host.notices[-1])

            self.assertEqual(runtime.toggle(), "default")
            self.assertFalse(runtime.is_active)
            self.assertIsNone(runtime.file_path)
            self.assertIn("Exited plan mode", host.notices[-1])

    async def test_duplicate_enter_and_inactive_exit_do_not_change_state(
        self,
    ) -> None:
        runtime, _host = _runtime()
        inactive = await runtime.exit()
        self.assertEqual(inactive.content, "Not in plan mode.")

        path = Path("plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.enter()
        duplicate = runtime.enter()

        self.assertEqual(duplicate.content, "Already in plan mode.")
        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)

    async def test_keep_planning_and_approval_error_preserve_transaction(
        self,
    ) -> None:
        runtime, _host = _runtime()
        path = Path("retry-plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.enter()

        runtime.set_approval_fn(
            AsyncMock(return_value={"choice": "keep-planning", "feedback": "revise"})
        )
        outcome = await runtime.exit()
        self.assertIn("revise", outcome.content)
        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)

        runtime.set_approval_fn(AsyncMock(side_effect=RuntimeError("approval failed")))
        with self.assertRaisesRegex(RuntimeError, "approval failed"):
            await runtime.exit()
        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)

    async def test_approval_choices_apply_expected_exit_transactions(self) -> None:
        # PR3：clear-and-execute 的上下文清空增强依赖 Kernel 特判，已降级为 execute。
        # PR4：审批通过不再切换权限模式；三种通过方式都只结束 Plan 状态。
        cases = (
            ("execute", False),
            ("clear-and-execute", False),
            ("manual-execute", False),
            ("unknown", False),
        )
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.md"
            plan_path.write_text("make the change", encoding="utf-8")
            for choice, terminate in cases:
                with self.subTest(choice=choice):
                    runtime, _host = _runtime()
                    with patch.object(
                        runtime,
                        "_generate_file_path",
                        return_value=plan_path,
                    ):
                        runtime.enter()
                    runtime.set_approval_fn(AsyncMock(return_value={"choice": choice}))

                    outcome = await runtime.exit()

                    self.assertFalse(runtime.is_active)
                    self.assertIsNone(runtime.file_path)
                    self.assertEqual(outcome.terminate, terminate)

    async def test_missing_file_and_no_callback_preserve_existing_behavior(
        self,
    ) -> None:
        runtime, _host = _runtime()
        missing_path = Path("missing-plan.md")
        with patch.object(
            runtime,
            "_generate_file_path",
            return_value=missing_path,
        ):
            runtime.enter()
        approval = AsyncMock(return_value={"choice": "execute"})
        runtime.set_approval_fn(approval)

        await runtime.exit()

        approval.assert_awaited_once_with("(No plan file found)")

        runtime, _host = _runtime()
        with patch.object(
            runtime,
            "_generate_file_path",
            return_value=missing_path,
        ):
            runtime.enter()
        outcome = await runtime.exit()
        self.assertIn("(No plan file found)", outcome.content)
        self.assertFalse(runtime.is_active)

    async def test_plan_read_error_propagates_without_partial_exit(self) -> None:
        runtime, _host = _runtime()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(runtime, "_generate_file_path", return_value=path):
                runtime.enter()

            with self.assertRaises(OSError):
                await runtime.exit()

        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)

    def test_new_session_path_error_preserves_active_transaction(self) -> None:
        runtime, _host = _runtime()
        path = Path("current-plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.enter()

        with (
            patch.object(
                runtime,
                "_generate_file_path",
                side_effect=OSError("path unavailable"),
            ),
            self.assertRaisesRegex(OSError, "path unavailable"),
        ):
            runtime.reset_for_new_session()

        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)

    async def test_restore_keeps_active_plan_path(self) -> None:
        runtime, _host = _runtime()
        first_path = Path("first.md")
        with patch.object(runtime, "_generate_file_path", return_value=first_path):
            runtime.enter()

        participant = PlanSessionParticipant(runtime)
        await participant.on_restore_session()

        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, first_path)

    async def test_clear_and_restore_keep_one_live_view(self) -> None:
        runtime, host = _runtime()
        first_path = Path("first.md")
        second_path = Path("second.md")
        with patch.object(
            runtime,
            "_generate_file_path",
            side_effect=[first_path, second_path],
        ):
            runtime.enter()
            view = runtime
            host.session_id = "session-two"
            runtime.reset_for_new_session()

        self.assertIs(runtime, view)
        self.assertEqual(runtime.file_path, second_path)

        runtime.toggle()
        self.assertFalse(runtime.is_active)

    def test_plan_prompt_layer_reads_live_view(self) -> None:
        runtime, _host = _runtime()
        layer = PlanPromptLayer(runtime)
        self.assertEqual(layer.layer_id, "plan")
        self.assertEqual(layer.render(), "")

        path = Path("live-plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.enter()
        self.assertIn(str(path), layer.render())

        runtime.toggle()
        self.assertEqual(layer.render(), "")

    async def test_plan_session_participant_delegates_to_runtime(self) -> None:
        runtime, _host = _runtime()
        participant = PlanSessionParticipant(runtime)
        with patch.object(runtime, "reset_for_new_session") as on_new:
            await participant.on_new_session()
        on_new.assert_called_once_with()
        await participant.on_restore_session()


if __name__ == "__main__":
    unittest.main()
