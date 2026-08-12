from __future__ import annotations

import unittest

from lion_code.tooling.internal import create_wakeup_tool
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import ToolResult


async def _wakeup_command(_arguments):
    return ToolResult(content="scheduled")


class TestTemporaryTools(unittest.TestCase):
    def test_schedule_wakeup_only_exists_inside_scope(self):
        registry = ToolRegistry()

        with self.assertRaises(LookupError):
            registry.resolve("schedule_wakeup")

        with registry.temporary_tool(create_wakeup_tool(_wakeup_command)):
            self.assertTrue(registry.is_active("schedule_wakeup"))

        with self.assertRaises(LookupError):
            registry.resolve("schedule_wakeup")


if __name__ == "__main__":
    unittest.main()
