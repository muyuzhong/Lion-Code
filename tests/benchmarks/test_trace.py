"""受控轨迹的脱敏与循环候选测试。"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from benchmarks.agent_e2e.models import VerifierOutcome
from benchmarks.agent_e2e.trace import TraceRecorder, redact_text, sanitize_payload
from benchmarks.agent_e2e.verifier import normalize_verifier_result


class TestTraceRecorder(unittest.TestCase):
    def test_trace_never_keeps_secret_session_or_absolute_path(self) -> None:
        recorder = TraceRecorder(trace_id="trace-test")
        recorder.record(
            {
                "event_type": "ToolExecutionStartEvent",
                "tool_name": "run_shell",
                "arguments": {
                    "api_key": "sk-super-secret-value",
                    "cwd": "D:/private/workspace",
                    "command": "Authorization: Bearer top-secret-token",
                },
                "message": "用户的原始请求不应写入轨迹。",
                "session_id": "user-session-should-not-escape",
            }
        )

        serialized = json.dumps(
            {
                "events": [event.model_dump(mode="json") for event in recorder.events],
                "summary": recorder.summary().model_dump(mode="json"),
            },
            ensure_ascii=False,
        )

        self.assertNotIn("sk-super-secret-value", serialized)
        self.assertNotIn("top-secret-token", serialized)
        self.assertNotIn("user-session-should-not-escape", serialized)
        self.assertNotIn("D:/private/workspace", serialized)
        self.assertNotIn("用户的原始请求不应写入轨迹。", serialized)
        self.assertGreaterEqual(recorder.summary().redaction_count, 3)
        self.assertEqual(recorder.events[0].event_type, "ToolExecutionStartEvent")

    def test_camel_case_tool_name_is_mapped(self) -> None:
        recorder = TraceRecorder(trace_id="trace-camel")
        recorder.record(
            {
                "event_type": "ToolExecutionEndEvent",
                "toolName": "run_shell",
                "args": {"command": "ls"},
            }
        )

        self.assertEqual(recorder.events[0].tool_name, "run_shell")
        self.assertIn("toolName=run_shell", recorder.events[0].summary)

    def test_event_timestamps_come_from_message_or_recorded_at(self) -> None:
        recorder = TraceRecorder(trace_id="trace-time")
        message_timestamp_ms = 1_784_000_000_000
        recorder.record(
            {
                "event_type": "MessageUpdateEvent",
                "message": {"role": "assistant", "timestamp": message_timestamp_ms},
            }
        )
        recorder.record(
            {
                "event_type": "ToolExecutionStartEvent",
                "toolName": "run_shell",
                "args": {"command": "ls"},
            }
        )

        expected = datetime.fromtimestamp(
            message_timestamp_ms / 1000, tz=UTC
        )
        self.assertEqual(recorder.events[0].started_at, expected)
        self.assertEqual(recorder.events[0].finished_at, expected)
        for event in recorder.events:
            self.assertIsNotNone(event.started_at)
            self.assertIsNotNone(event.finished_at)

    def test_three_identical_tool_calls_create_one_loop_candidate(self) -> None:
        recorder = TraceRecorder(trace_id="trace-loop")
        fingerprints = [
            recorder.record_tool_call(
                tool_name="read_file",
                arguments={"path": "same.py"},
                workspace_fingerprint="a" * 64,
            )
            for _ in range(3)
        ]

        self.assertEqual(fingerprints[0], fingerprints[1])
        self.assertEqual(len(recorder.loop_candidates), 1)
        self.assertEqual(recorder.loop_candidates[0].repetitions, 3)
        self.assertEqual(recorder.summary().loop_fingerprints, (fingerprints[0],))

    def test_redaction_helpers_control_inline_values_and_paths(self) -> None:
        text, count = redact_text("api_key=very-secret sk-another-secret-value")
        payload, path_count = sanitize_payload(
            {"workspace": "/very/private/path", "token": "secret"}
        )

        self.assertNotIn("very-secret", text)
        self.assertGreaterEqual(count, 2)
        self.assertTrue(str(payload["workspace"]).startswith("<path:"))
        self.assertEqual(payload["token"], "[REDACTED]")
        self.assertEqual(path_count, 2)

    def test_verifier_normalization_keeps_digest_not_secret_output(self) -> None:
        result = normalize_verifier_result(
            outcome=VerifierOutcome.FAILED,
            command_summary="pytest -q --token=private-token",
            exit_code=1,
            output="Authorization: Bearer private-token",
        )

        serialized = result.canonical_json()
        self.assertNotIn("private-token", serialized)
        self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
