from __future__ import annotations

from pathlib import Path

from lion_code.project_identity import ProjectIdentity
from lion_code.prompt import PromptComposer, load_project_context_files


class _Layer:
    layer_id = "test"

    def __init__(self, fragment: str) -> None:
        self.fragment = fragment
        self.calls = 0

    def render(self) -> str:
        self.calls += 1
        return self.fragment


def test_project_context_loads_root_to_cwd_with_agents_precedence(tmp_path) -> None:
    root = tmp_path / "repo"
    child = root / "packages" / "api"
    child.mkdir(parents=True)
    (root / "CLAUDE.md").write_text("root claude")
    (root / "AGENTS.md").write_text("root agents")
    (child / "CLAUDE.md").write_text("child claude")
    (child / "AGENTS.md").write_text("child agents")
    (tmp_path / "AGENTS.md").write_text("outside agents")
    identity = ProjectIdentity(root=root.resolve(), key="project", is_git=True)

    files = load_project_context_files(cwd=child, identity=identity)

    assert [Path(item.path).relative_to(root) for item in files] == [
        Path("CLAUDE.md"),
        Path("AGENTS.md"),
        Path("packages/api/CLAUDE.md"),
        Path("packages/api/AGENTS.md"),
    ]
    assert [item.content for item in files] == [
        "root claude",
        "root agents",
        "child claude",
        "child agents",
    ]
    assert "outside agents" not in {item.content for item in files}


def test_prompt_composer_orders_base_dynamic_and_non_empty_layers() -> None:
    composer = PromptComposer(
        stable_base_prompt="base",
        dynamic_context="dynamic",
        layers=lambda: [_Layer("layer-a"), _Layer(""), _Layer("layer-b")],
    )

    assert composer.get_system() == "base\n\ndynamic\n\nlayer-a\n\nlayer-b"


def test_prompt_composer_reads_layers_per_call_without_history() -> None:
    current = [_Layer("first")]
    composer = PromptComposer("custom", layers=lambda: current)

    assert composer.get_system() == "custom\n\nfirst"
    current[:] = [_Layer("second")]
    composer.set_dynamic_context("updated")

    assert composer.get_system() == "custom\n\nupdated\n\nsecond"
    assert "history" not in composer.get_system().lower()


def test_prompt_composer_custom_prompt_replaces_default_context_but_keeps_layers() -> (
    None
):
    layer = _Layer("plan projection")
    composer = PromptComposer("custom system", layers=lambda: (layer,))

    assert composer.get_system() == "custom system\n\nplan projection"
