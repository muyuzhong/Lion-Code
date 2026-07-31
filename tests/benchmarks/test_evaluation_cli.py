"""离线评测命令行的安全边界测试。"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from benchmarks.agent_e2e.cli import main


class TestEvaluationCli(unittest.TestCase):
    def test_online_entry_is_explicitly_blocked_without_loading_manifest(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(
                ["online-run", "--manifest", "not-read-by-foundation.json"]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertNotIn("task_resolved", output.getvalue())


if __name__ == "__main__":
    unittest.main()
