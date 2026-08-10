from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lion_code.permission_state import (
    PermissionController,
    PermissionMode,
    PermissionState,
)
from lion_code.plan_runtime import PlanRuntime, PlanState


class _Host:
    def __init__(self) -> None:
        self.session_id = "session-one"
        self._base_system_prompt = "base prompt"
        self._system_prompt = ""
        self.notices: list[str] = []

    def _emit_notice(self, message: str, *, role: str = "info") -> None:
        self.notices.append(f"{role}:{message}")


def _runtime(
    mode: PermissionMode = "default",
) -> tuple[
    PlanRuntime,
    PermissionController,
    _Host,
]:
    host = _Host()
    permission = PermissionController(PermissionState(mode))
    runtime = PlanRuntime(host, permission, PlanState())
    return runtime, permission, host


class TestPlanRuntime(unittest.IsolatedAsyncioTestCase):
    def test_initial_plan_path_error_does_not_publish_partial_state(self) -> None:
        runtime, permission, host = _runtime("plan")

        with (
            patch.object(
                runtime,
                "_generate_file_path",
                side_effect=OSError("path unavailable"),
            ),
            self.assertRaisesRegex(OSError, "path unavailable"),
        ):
            runtime.initialize()

        self.assertFalse(runtime.is_active)
        self.assertIsNone(runtime.file_path)
        self.assertEqual(permission.mode, "plan")
        self.assertEqual(host._system_prompt, "")

    def test_initial_plan_builds_live_view_and_exits_to_default(self) -> None:
        runtime, permission, host = _runtime("plan")
        plan_path = Path("initial-plan.md")

        with patch.object(runtime, "_generate_file_path", return_value=plan_path):
            runtime.initialize()

        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, plan_path)
        self.assertIn(str(plan_path), host._system_prompt)
        self.assertEqual(runtime.toggle(), "default")
        self.assertFalse(runtime.is_active)
        self.assertIsNone(runtime.file_path)
        self.assertEqual(permission.mode, "default")
        self.assertEqual(host._system_prompt, host._base_system_prompt)

    def test_toggle_restores_each_entering_permission_mode(self) -> None:
        modes: tuple[PermissionMode, ...] = (
            "default",
            "acceptEdits",
            "bypassPermissions",
            "dontAsk",
            "auto",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                runtime, permission, _host = _runtime(mode)
                runtime.initialize()
                view = runtime
                with patch.object(
                    runtime,
                    "_generate_file_path",
                    return_value=Path(f"{mode}.md"),
                ):
                    self.assertEqual(runtime.toggle(), "plan")
                    self.assertIs(runtime, view)
                    self.assertEqual(permission.mode, "plan")
                    self.assertEqual(runtime.toggle(), mode)
                self.assertIs(runtime, view)
                self.assertEqual(permission.mode, mode)

    async def test_duplicate_enter_and_inactive_exit_do_not_change_state(self) -> None:
        runtime, permission, host = _runtime("auto")
        runtime.initialize()
        inactive = await runtime.exit()
        self.assertEqual(inactive.content, "Not in plan mode.")

        path = Path("plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.enter()
        prompt = host._system_prompt
        duplicate = runtime.enter()

        self.assertEqual(duplicate.content, "Already in plan mode.")
        self.assertEqual(permission.mode, "plan")
        self.assertEqual(runtime.file_path, path)
        self.assertEqual(host._system_prompt, prompt)

    async def test_keep_planning_and_approval_error_preserve_transaction(self) -> None:
        runtime, permission, host = _runtime("dontAsk")
        runtime.initialize()
        path = Path("retry-plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.enter()
        prompt = host._system_prompt

        runtime.set_approval_fn(
            AsyncMock(return_value={"choice": "keep-planning", "feedback": "revise"})
        )
        outcome = await runtime.exit()
        self.assertIn("revise", outcome.content)
        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)
        self.assertEqual(permission.mode, "plan")
        self.assertEqual(host._system_prompt, prompt)

        runtime.set_approval_fn(AsyncMock(side_effect=RuntimeError("approval failed")))
        with self.assertRaisesRegex(RuntimeError, "approval failed"):
            await runtime.exit()
        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)
        self.assertEqual(permission.mode, "plan")
        self.assertEqual(host._system_prompt, prompt)

    async def test_approval_choices_apply_expected_exit_transactions(self) -> None:
        cases = (
            ("execute", "acceptEdits", False),
            ("clear-and-execute", "acceptEdits", True),
            ("manual-execute", "dontAsk", False),
            ("unknown", "dontAsk", False),
        )
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.md"
            plan_path.write_text("make the change", encoding="utf-8")
            for choice, expected_mode, terminate in cases:
                with self.subTest(choice=choice):
                    runtime, permission, host = _runtime("dontAsk")
                    runtime.initialize()
                    with patch.object(
                        runtime,
                        "_generate_file_path",
                        return_value=plan_path,
                    ):
                        runtime.enter()
                    runtime.set_approval_fn(AsyncMock(return_value={"choice": choice}))

                    outcome = await runtime.exit()

                    self.assertEqual(permission.mode, expected_mode)
                    self.assertFalse(runtime.is_active)
                    self.assertIsNone(runtime.file_path)
                    self.assertEqual(host._system_prompt, host._base_system_prompt)
                    self.assertEqual(outcome.terminate, terminate)
                    if terminate:
                        self.assertIn(
                            "Approved plan:\nmake the change",
                            runtime.pending_context_reset or "",
                        )
                        runtime.complete_context_reset()
                    self.assertIsNone(runtime.pending_context_reset)

    async def test_missing_file_and_no_callback_preserve_existing_behavior(
        self,
    ) -> None:
        runtime, permission, _host = _runtime("auto")
        runtime.initialize()
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
        self.assertEqual(permission.mode, "acceptEdits")

        runtime, permission, _host = _runtime("auto")
        runtime.initialize()
        with patch.object(
            runtime,
            "_generate_file_path",
            return_value=missing_path,
        ):
            runtime.enter()
        outcome = await runtime.exit()
        self.assertIn("(No plan file found)", outcome.content)
        self.assertEqual(permission.mode, "auto")

    async def test_plan_read_error_propagates_without_partial_exit(self) -> None:
        runtime, permission, host = _runtime("bypassPermissions")
        runtime.initialize()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(runtime, "_generate_file_path", return_value=path):
                runtime.enter()
            prompt = host._system_prompt

            with self.assertRaises(OSError):
                await runtime.exit()

        self.assertTrue(runtime.is_active)
        self.assertEqual(runtime.file_path, path)
        self.assertEqual(permission.mode, "plan")
        self.assertEqual(host._system_prompt, prompt)

    def test_new_session_path_error_preserves_active_transaction(self) -> None:
        runtime, permission, host = _runtime("plan")
        path = Path("current-plan.md")
        with patch.object(runtime, "_generate_file_path", return_value=path):
            runtime.initialize()
        prompt = host._system_prompt

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
        self.assertEqual(permission.mode, "plan")
        self.assertEqual(host._system_prompt, prompt)

    async def test_restore_clears_pending_reset(self) -> None:
        runtime, _permission, _host = _runtime("default")
        runtime.initialize()
        with patch.object(
            runtime,
            "_generate_file_path",
            return_value=Path("missing-plan.md"),
        ):
            runtime.enter()
        runtime.set_approval_fn(AsyncMock(return_value={"choice": "clear-and-execute"}))
        await runtime.exit()
        self.assertIsNotNone(runtime.pending_context_reset)

        runtime.reset_after_restore()

        self.assertIsNone(runtime.pending_context_reset)

    async def test_clear_restore_and_prompt_refresh_keep_one_live_view(self) -> None:
        runtime, permission, host = _runtime("plan")
        first_path = Path("first.md")
        second_path = Path("second.md")
        with patch.object(
            runtime,
            "_generate_file_path",
            side_effect=[first_path, second_path],
        ):
            runtime.initialize()
            view = runtime
            host.session_id = "session-two"
            runtime.reset_for_new_session()

        self.assertIs(runtime, view)
        self.assertEqual(runtime.file_path, second_path)
        self.assertEqual(permission.mode, "plan")
        runtime.reset_after_restore()
        self.assertEqual(runtime.file_path, second_path)

        host._base_system_prompt = "new base"
        runtime.refresh_prompt()
        self.assertTrue(host._system_prompt.startswith("new base"))
        self.assertIn(str(second_path), host._system_prompt)

        runtime.toggle()
        host._base_system_prompt = "latest base"
        runtime.refresh_prompt()
        self.assertEqual(host._system_prompt, "latest base")


if __name__ == "__main__":
    unittest.main()
