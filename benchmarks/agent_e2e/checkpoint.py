"""单题评测 checkpoint：只保存严格、无敏感的 TaskResult。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import TaskResult


class CheckpointError(RuntimeError):
    """checkpoint 无法安全读取、校验或原子写入。"""


@runtime_checkable
class CheckpointStore(Protocol):
    """运行器使用的异步 checkpoint 边界。"""

    async def load(
        self,
        *,
        run_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskResult | None:
        ...

    async def save(self, result: TaskResult, *, run_id: str) -> None:
        ...


class InMemoryCheckpointStore:
    """离线单元测试使用的无 I/O checkpoint store。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, int], TaskResult] = {}

    async def load(
        self,
        *,
        run_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskResult | None:
        return self._items.get((run_id, task_id, attempt))

    async def save(self, result: TaskResult, *, run_id: str) -> None:
        self._items[(run_id, result.task_id, result.attempt)] = result


class JsonCheckpointStore:
    """Host 结果目录下的严格 JSON checkpoint store。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    async def load(
        self,
        *,
        run_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskResult | None:
        path = self._path_for(run_id=run_id, task_id=task_id, attempt=attempt)
        if not path.exists():
            return None
        try:
            return TaskResult.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CheckpointError(f"Invalid checkpoint {path}: {error}") from error

    async def save(self, result: TaskResult, *, run_id: str) -> None:
        path = self._path_for(
            run_id=run_id,
            task_id=result.task_id,
            attempt=result.attempt,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(result.canonical_json() + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError as error:
            raise CheckpointError(f"Unable to save checkpoint {path}: {error}") from error

    def _path_for(self, *, run_id: str, task_id: str, attempt: int) -> Path:
        _safe_component(run_id, "run_id")
        _safe_component(task_id, "task_id")
        if attempt < 1:
            raise CheckpointError("attempt must be positive")
        return self.root / run_id / f"{task_id}.attempt-{attempt}.json"


def _safe_component(value: str, name: str) -> None:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise CheckpointError(f"Invalid {name}")
