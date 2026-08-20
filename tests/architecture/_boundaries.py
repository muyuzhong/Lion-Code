"""Single source of truth for architecture boundary definitions.

Both the AST boundary tests in this package and the import-linter
configuration in ``pyproject.toml`` must stay consistent with the
definitions here.  ``test_import_linter_config_matches_boundaries``
verifies the two representations do not drift.

Adding a new top-level module to ``lion_code/`` does **not** require
touching this file: ``ALL_ROOTS`` is discovered from the filesystem at
import time.  Boundaries that use an ``allowed`` whitelist automatically
forbid the new module; boundaries that use an explicit ``forbidden``
blacklist do not (which is intentional for Core/Application whose
allowed set is broad).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "lion_code"


def _discover_all_roots() -> frozenset[str]:
    """Discover all top-level lion_code module roots from the filesystem."""
    roots: set[str] = set()
    for entry in sorted(SOURCE_ROOT.iterdir()):
        if entry.name.startswith("__"):
            continue
        if entry.is_dir():
            if (entry / "__init__.py").exists():
                roots.add(entry.name)
        elif entry.suffix == ".py":
            roots.add(entry.stem)
    return frozenset(roots)


# All top-level lion_code module roots (excluding __init__, __main__).
# Discovered at import time so it never goes stale.
ALL_ROOTS: frozenset[str] = _discover_all_roots()


@dataclass(frozen=True)
class Boundary:
    """A single import-direction architecture contract.

    Exactly one of ``allowed`` or ``forbidden`` must be set.

    * ``allowed``   – whitelist of short root names (e.g. ``"core"``).
                      The import-linter forbidden list is derived as
                      ``ALL_ROOTS - allowed``.
    * ``forbidden`` – explicit blacklist of short root names.
                      Used when the allowed set is too broad to enumerate.

    ``external`` marks boundaries whose forbidden targets are outside
    ``lion_code`` (e.g. ``tests``, ``benchmarks``).
    """

    contract_name: str
    source_package: str
    allowed: frozenset[str] | None = None
    forbidden: frozenset[str] | None = None
    allow_indirect: bool = False
    external: bool = False

    @property
    def forbidden_roots(self) -> frozenset[str]:
        """Short root names that must not be imported (for AST tests)."""
        if self.forbidden is not None:
            return self.forbidden
        assert self.allowed is not None
        return ALL_ROOTS - self.allowed

    @property
    def allowed_roots(self) -> frozenset[str]:
        """Short root names that may be imported (for AST tests)."""
        if self.allowed is not None:
            return self.allowed
        # Boundaries with an explicit forbidden list allow everything else.
        return ALL_ROOTS - self.forbidden_roots

    @property
    def import_linter_forbidden_modules(self) -> frozenset[str]:
        """Full dotted module paths for ``pyproject.toml`` forbidden_modules."""
        if self.external:
            assert self.forbidden is not None
            return self.forbidden
        return frozenset(f"lion_code.{r}" for r in self.forbidden_roots)


# The architecture contracts.  Order matches pyproject.toml.
BOUNDARIES: tuple[Boundary, ...] = (
    Boundary(
        contract_name="Core 不依赖上层运行时包",
        source_package="lion_code.core",
        forbidden=frozenset(
            {
                "providers",
                "tooling",
                "application",
                "observers",
                "tui",
                "permission_state",
                "usage",
                "session_runtime",
                "capabilities",
                "supervisor",
                "adapters",
                "runtime",
                "composition",
            }
        ),
    ),
    Boundary(
        contract_name="Supervisor 只依赖公开 Core 事件契约",
        source_package="lion_code.supervisor",
        forbidden=frozenset(
            {
                "runtime",
                "application",
                "capabilities",
                "composition",
                "adapters",
                "context",
                "permission_state",
                "providers",
                "session_runtime",
                "tooling",
                "tui",
                "usage",
            }
        ),
    ),
    Boundary(
        contract_name="Composition 不依赖 Product Facade 与 Interfaces",
        source_package="lion_code.composition",
        forbidden=frozenset(
            {
                "application",
                "meta_agent",
                "supervisor",
                "tui",
            }
        ),
        allow_indirect=True,
    ),
    Boundary(
        contract_name="MetaAgent 不依赖 Product Features 与 Interfaces",
        source_package="lion_code.meta_agent",
        forbidden=frozenset(
            {
                "application",
                "supervisor",
                "tui",
            }
        ),
    ),
    Boundary(
        contract_name="Providers 只依赖 Core 抽象",
        source_package="lion_code.providers",
        allowed=frozenset({"core", "providers"}),
    ),
    Boundary(
        contract_name="Application 不依赖 TUI",
        source_package="lion_code.application",
        forbidden=frozenset({"tui"}),
    ),
    Boundary(
        contract_name="TUI 只经 Application/Core 接触运行时",
        source_package="lion_code.tui",
        allowed=frozenset(
            {
                "application",
                "config",
                "core",
                "prompt",
                "tui",
                "version",
            }
        ),
        allow_indirect=True,
    ),
    Boundary(
        contract_name="Capabilities 不依赖 Agent 宿主与 Application/TUI",
        source_package="lion_code.capabilities",
        forbidden=frozenset(
            {
                "application",
                "tui",
            }
        ),
    ),
    Boundary(
        contract_name="生产代码不导入测试与基准",
        source_package="lion_code",
        forbidden=frozenset({"tests", "benchmarks"}),
        external=True,
    ),
)
