"""公开 catalog 与冻结 lock 的单一校验入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import Catalog, CatalogLock, TaskSpec


class CatalogValidationError(ValueError):
    """catalog 内容、选择或 lock 不满足可复现实验约束。"""


@dataclass(frozen=True, slots=True)
class CatalogValidation:
    """成功校验后的不可变摘要。"""

    catalog_sha256: str
    task_count: int
    task_ids: tuple[str, ...]


def catalog_sha256(catalog: Catalog) -> str:
    """计算完整公开 catalog 的稳定 SHA-256，不依赖文件格式化。"""

    return catalog.fingerprint()


def validate_catalog(
    catalog: Catalog,
    *,
    lock: CatalogLock | None = None,
) -> CatalogValidation:
    """校验任务 ID、公开证据字段和可选冻结 lock。"""

    task_ids = tuple(task.task_id for task in catalog.tasks)
    if len(set(task_ids)) != len(task_ids):
        raise CatalogValidationError("Catalog contains duplicate task_id values")
    for task in catalog.tasks:
        _validate_task(task)

    digest = catalog_sha256(catalog)
    if lock is not None:
        _validate_lock(catalog, lock, digest)
    return CatalogValidation(
        catalog_sha256=digest,
        task_count=len(catalog.tasks),
        task_ids=task_ids,
    )


def freeze_catalog(
    catalog: Catalog,
    *,
    task_ids: Iterable[str] | None = None,
) -> CatalogLock:
    """在执行前冻结 catalog 内容和有序任务选择。"""

    validation = validate_catalog(catalog)
    selected = tuple(task_ids) if task_ids is not None else validation.task_ids
    if not selected:
        raise CatalogValidationError("Catalog lock must select at least one task")
    if len(set(selected)) != len(selected):
        raise CatalogValidationError("Catalog lock selection contains duplicate task IDs")
    missing = set(selected).difference(validation.task_ids)
    if missing:
        raise CatalogValidationError(
            f"Catalog lock selection contains unknown task IDs: {sorted(missing)!r}"
        )
    return CatalogLock(
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.catalog_version,
        catalog_sha256=validation.catalog_sha256,
        task_ids=selected,
    )


def load_catalog(path: str | Path) -> Catalog:
    """读取严格 JSON catalog；未知字段和版本漂移均在模型边界失败。"""

    return _load_versioned(path, Catalog)


def load_catalog_lock(path: str | Path) -> CatalogLock:
    """读取严格 JSON catalog lock。"""

    return _load_versioned(path, CatalogLock)


def write_catalog_lock(path: str | Path, lock: CatalogLock) -> None:
    """以稳定 UTF-8 JSON 写入可提交的 lock 文件。"""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(lock.canonical_json() + "\n", encoding="utf-8")


def _validate_task(task: TaskSpec) -> None:
    if not task.gold_evidence_hash.strip():
        raise CatalogValidationError(f"Task {task.task_id!r} is missing gold evidence hash")
    if not task.base_revision.strip():
        raise CatalogValidationError(f"Task {task.task_id!r} is missing base revision")
    if not task.verifier_identity.strip():
        raise CatalogValidationError(f"Task {task.task_id!r} is missing verifier identity")


def _validate_lock(catalog: Catalog, lock: CatalogLock, digest: str) -> None:
    if lock.catalog_id != catalog.catalog_id:
        raise CatalogValidationError("Catalog lock catalog_id does not match catalog")
    if lock.catalog_version != catalog.catalog_version:
        raise CatalogValidationError("Catalog lock catalog_version does not match catalog")
    if lock.catalog_sha256 != digest:
        raise CatalogValidationError("Catalog lock SHA-256 does not match catalog")
    catalog_ids = {task.task_id for task in catalog.tasks}
    missing = set(lock.task_ids).difference(catalog_ids)
    if missing:
        raise CatalogValidationError(
            f"Catalog lock references task IDs missing from catalog: {sorted(missing)!r}"
        )


def _load_versioned(path: str | Path, model_type: type[Catalog] | type[CatalogLock]):
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise CatalogValidationError(f"Unable to read {source}: {error}") from error
    except json.JSONDecodeError as error:
        raise CatalogValidationError(f"Invalid JSON in {source}: {error}") from error
    if not isinstance(payload, dict):
        raise CatalogValidationError(f"{source} must contain a JSON object")
    return model_type.from_dict(payload)
