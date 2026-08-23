"""测试根 conftest：隔离默认 memory DB，防止触碰开发者真实 ``~/.lion-code``。

FullProfile 组合会把 MemoryStore 绑定到 ``default_memory_db_path()``；构造
本身不打开数据库，但调用 Memory 工具时仍需隔离开发者真实 home 库。
pytest 由此 fixture 统一隔离；
``unittest discover`` 本地路径由 ``tests/full_agent.py`` 的
``isolated_memory_db`` 与 adapters 测试内的同一 helper 覆盖。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_default_memory_db(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    db_path = tmp_path_factory.mktemp("memory-db") / "memory.sqlite3"
    with patch(
        "lion_code.composition.agent_builder.default_memory_db_path",
        lambda: db_path,
    ):
        yield db_path
