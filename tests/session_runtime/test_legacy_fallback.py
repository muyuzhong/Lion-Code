from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lion_code.session_runtime import (
    LegacySessionError,
    legacy_session_messages,
    list_legacy_sessions,
    load_legacy_session,
)


class TestLegacyFallback(unittest.TestCase):
    def test_anthropic_tool_pair_converts_to_canonical_messages(self) -> None:
        messages = legacy_session_messages(
            {
                "metadata": {"model": "claude-old"},
                "anthropicMessages": [
                    {"role": "user", "content": "question"},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "checking"},
                            {
                                "type": "tool_use",
                                "id": "c1",
                                "name": "read_file",
                                "input": {"path": "README.md"},
                            },
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "c1",
                                "content": "file body",
                            }
                        ],
                    },
                    {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
                ],
            }
        )

        self.assertEqual(
            [message.role for message in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[1].tool_calls[0].id, "c1")
        self.assertEqual(messages[2].tool_name, "read_file")

    def test_invalid_legacy_json_is_reported_and_skipped_by_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            (session_dir / "broken.json").write_text("{", encoding="utf-8")

            with self.assertRaises(LegacySessionError):
                load_legacy_session(session_dir, "broken")
            self.assertEqual(list_legacy_sessions(session_dir), [])


if __name__ == "__main__":
    unittest.main()
