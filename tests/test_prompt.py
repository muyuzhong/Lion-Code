from __future__ import annotations

from pathlib import Path

from lion_code.project_identity import ProjectIdentity
from lion_code.prompt import load_project_context_files


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
