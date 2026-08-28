"""digest 寻迹账本的追加/反查/聚合与脱敏边界测试。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.agent_e2e.digest_ledger import (
    DigestLedger,
    DigestLedgerEntry,
    redacted_preview,
)
from benchmarks.agent_e2e.models import DeepEvalTrajectory, DeepEvalTrajectoryEvent
from benchmarks.agent_e2e.verified_runner import _write_digest_ledger


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="digest-ledger-"))


class TestDigestLedger(unittest.TestCase):
    def test_append_lookup_aggregates_count_per_kind(self) -> None:
        ledger = DigestLedger(_temp_dir() / "ledger.jsonl")
        first = DigestLedgerEntry(
            digest="d" * 64,
            kind="input",
            task_id="task-1",
            run_id="run-1",
            preview="公开任务",
            last_seen_at=datetime(2026, 8, 28, 1, 0, tzinfo=UTC),
        )
        second = DigestLedgerEntry(
            digest="d" * 64,
            kind="input",
            task_id="task-1",
            run_id="run-2",
            preview="公开任务",
            last_seen_at=datetime(2026, 8, 28, 2, 0, tzinfo=UTC),
        )
        ledger.append([first])
        ledger.append([second])
        hits = ledger.lookup("d" * 64)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].run_id, "run-2")  # 每 kind 取最近一条
        self.assertEqual(hits[0].count, 2)  # count 跨出现聚合
        self.assertEqual(ledger.count(), 2)

    def test_lookup_missing_and_unknown_digest(self) -> None:
        ledger = DigestLedger(_temp_dir() / "ledger.jsonl")
        ledger.append(
            [
                DigestLedgerEntry(
                    digest="e" * 64,
                    kind="trace",
                    task_id="task-1",
                    run_id="run-1",
                    preview="轨迹 3 个投影事件",
                )
            ]
        )
        self.assertEqual(ledger.lookup("f" * 64), ())
        self.assertEqual(ledger.lookup("e" * 64)[0].kind, "trace")

    def test_preview_is_redacted_and_no_secret_literal_persists(self) -> None:
        ledger = DigestLedger(_temp_dir() / "ledger.jsonl")
        ledger.append(
            [
                DigestLedgerEntry(
                    digest="a" * 64,
                    kind="input",
                    task_id="task-1",
                    run_id="run-1",
                    preview=redacted_preview(
                        "修复 api_key=sk-not-persisted 的会话问题", max_length=160
                    ),
                )
            ]
        )
        serialized = ledger.path.read_text(encoding="utf-8")
        self.assertNotIn("sk-not-persisted", serialized)
        self.assertIn("[REDACTED]", serialized)
        hits = ledger.lookup("a" * 64)
        self.assertNotIn("sk-not-persisted", hits[0].preview or "")

    def test_ledger_writer_wires_trajectory_digests(self) -> None:
        # 经 verified_runner 勾挂:input/trace/payload/argument 均入账。
        trajectory = DeepEvalTrajectory(
            task_id="verified-task-1",
            trace_id="trace-1",
            trace_digest="b" * 64,
            events=(
                DeepEvalTrajectoryEvent(
                    sequence=1,
                    event_type="ToolExecution",
                    payload_digest="c" * 64,
                    tool_name="read_file",
                    argument_digest="d" * 64,
                ),
            ),
        )
        root = _temp_dir()
        request = _RequestStub(
            digest_ledger_path=root / "ledger.jsonl",
            task_id="verified-task-1",
            run_id="run-1",
            public_prompt="公开问题",
        )
        _write_digest_ledger(request, trajectory, input_digest="a" * 64)
        ledger = DigestLedger(root / "ledger.jsonl")
        self.assertEqual(len(ledger.lookup("a" * 64)), 1)  # input
        self.assertEqual(len(ledger.lookup("b" * 64)), 1)  # trace
        self.assertEqual(len(ledger.lookup("c" * 64)), 1)  # payload
        self.assertEqual(ledger.lookup("c" * 64)[0].tool_name, "read_file")
        self.assertEqual(len(ledger.lookup("d" * 64)), 1)  # argument
        self.assertEqual(ledger.count(), 4)

    def test_ledger_header_and_entry_are_strict_json(self) -> None:
        ledger = DigestLedger(_temp_dir() / "ledger.jsonl")
        ledger.append(
            [DigestLedgerEntry(digest="a" * 64, kind="input", task_id="t", run_id="r")]
        )
        lines = ledger.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["kind"], "digest-ledger")
        self.assertIn('"schema_version":"agent-e2e/v1"', lines[1])

    def test_ledger_file_absent_lookup_is_empty_and_count_zero(self) -> None:
        ledger = DigestLedger(_temp_dir() / "missing.jsonl")
        self.assertEqual(ledger.lookup("a" * 64), ())
        self.assertEqual(ledger.count(), 0)


class _RequestStub:
    """DigestLedger 勾挂所需的 VerifiedExecutionRequest 最小片段。"""

    def __init__(
        self,
        *,
        digest_ledger_path: Path,
        task_id: str,
        run_id: str,
        public_prompt: str,
    ) -> None:
        self.digest_ledger_path = digest_ledger_path
        self.task_id = task_id
        self.run_id = run_id
        self.public_prompt = public_prompt

    @property
    def task(self) -> object:
        return type(
            "Task", (), {"task_id": self.task_id, "public_prompt": self.public_prompt}
        )()

    @property
    def manifest(self) -> object:
        return type("Manifest", (), {"run_id": self.run_id})()


if __name__ == "__main__":
    unittest.main()
