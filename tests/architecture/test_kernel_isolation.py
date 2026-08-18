"""PR0 四层边界门禁：Kernel 隔离 / Supervisor 订阅契约。

与 ``_boundaries.py`` 的 import 方向契约互补：本文件用 AST 扫描 Kernel 与 Supervisor
模块，确保：

- Kernel 代码不引用 Capability/Supervisor 专属符号（"不是 Kernel" 清单）。
- Supervisor 模块只消费 Kernel 事件契约，不触碰 Agent 内部私有对象。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"

# Capability / Supervisor 专属符号：Kernel 代码不得引用（"不是 Kernel" 清单）。
_NON_KERNEL_SYMBOLS = (
    "MemoryContextInjector",
    "MemoryCoordinator",
    "RelevantMemory",
    "PlanRuntime",
    "PlanState",
    "SubagentFactory",
    "SubagentExecutor",
    "Supervisor",
)
_NON_KERNEL_STRING = "<relevant-memory>"

# Supervisor 模块：可消费 Kernel 事件契约，但不得 import Agent 引擎或触碰私有对象。
_SUPERVISOR_MODULES = ("supervisor.py",)
_SUPERVISOR_FORBIDDEN_IMPORTS = (
    "lion_code.agent",
    "lion_code.agent_runtime",
    "lion_code.core.harness",
)
_SUPERVISOR_FORBIDDEN_ATTRS = (
    "_aborted",
    "core_runtime",
    "_capability_registry",
    "_runtime_coordinator",
)

_KERNEL_FILES = sorted((SOURCE_ROOT / "core").glob("*.py"))


def _iter_symbol_uses(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _NON_KERNEL_SYMBOLS:
            yield node.id
        elif isinstance(node, ast.Attribute) and node.attr in _NON_KERNEL_SYMBOLS:
            yield node.attr
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _NON_KERNEL_STRING in node.value
        ):
            yield _NON_KERNEL_STRING


def test_kernel_does_not_reference_capability_or_supervisor_symbols() -> None:
    violations: list[tuple[str, str]] = []
    for path in _KERNEL_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for symbol in _iter_symbol_uses(tree):
            violations.append((path.name, symbol))
    assert not violations, f"Kernel 引用非 Kernel 符号: {violations}"


def test_kernel_has_no_import_of_capability_or_supervisor_modules() -> None:
    forbidden = re.compile(
        r"lion_code\.(plan_runtime|capabilities|subagent_runtime"
        r"|skill_runtime|supervisor)\b"
    )
    hits: list[str] = []
    for path in _KERNEL_FILES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line):
                hits.append(f"{path.name}:{lineno}")
    assert not hits, f"Kernel 导入非 Kernel 模块: {hits}"


def test_supervisor_modules_do_not_import_agent_privates() -> None:
    import_hits: list[str] = []
    attr_hits: list[str] = []
    for name in _SUPERVISOR_MODULES:
        path = SOURCE_ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module in _SUPERVISOR_FORBIDDEN_IMPORTS
            ):
                import_hits.append(f"{name}: {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _SUPERVISOR_FORBIDDEN_IMPORTS:
                        import_hits.append(f"{name}: {alias.name}")
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in _SUPERVISOR_FORBIDDEN_ATTRS
            ):
                attr_hits.append(f"{name}: .{node.attr}")
    assert not import_hits, f"Supervisor import 引擎模块: {import_hits}"
    assert not attr_hits, f"Supervisor 触碰 Agent 私有对象: {attr_hits}"
