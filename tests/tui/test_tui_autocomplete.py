from pathlib import Path

from lion_code.application.commands import (
    CommandRegistry,
    CommandResult,
    SlashCommand,
    create_default_command_registry,
)
from lion_code.tui.autocomplete import CompletionOption, build_completion_state


def _mechanism_registry() -> CommandRegistry:
    """本地注册表:这些用例测的是补全机制,与 Lion 默认命令集解耦。"""

    def noop(_ctx: object) -> CommandResult:
        return CommandResult(handled=True)

    registry = CommandRegistry()
    for name, search_terms in (
        ("session", ()),
        ("skill", ()),
        ("skills", ()),
        ("resume", ()),
        ("new", ("clear", "reset")),
    ):
        registry.register(
            SlashCommand(
                name=name,
                description=name,
                usage=f"/{name}",
                handler=noop,
                search_terms=search_terms,
            )
        )
    return registry


def test_command_completion_for_slash_lists_every_registered_command() -> None:
    registry = create_default_command_registry()
    state = build_completion_state(
        "/",
        command_registry=registry,
    )

    assert [item.display for item in state.items] == [
        f"/{command.name}" for command in registry.list_commands()
    ]


def test_skill_names_appear_in_slash_completion() -> None:
    state = build_completion_state(
        "/",
        command_registry=create_default_command_registry(),
        skill_names=("code-review", "test-gen"),
    )

    displays = [item.display for item in state.items]
    assert "/code-review" in displays
    assert "/test-gen" in displays
    skill_items = [item for item in state.items if item.category == "Skills"]
    assert len(skill_items) == 2


def test_skill_completion_filters_by_prefix() -> None:
    state = build_completion_state(
        "/code",
        command_registry=create_default_command_registry(),
        skill_names=("code-review", "test-gen"),
    )

    displays = [item.display for item in state.items]
    assert "/code-review" in displays
    assert "/test-gen" not in displays



def test_command_completion_suggests_registered_commands() -> None:
    state = build_completion_state(
        "/sess",
        command_registry=_mechanism_registry(),
    )

    assert [item.display for item in state.items] == ["/session"]
    assert state.selected is not None
    assert state.selected.apply("/sess") == "/session"


def test_command_completion_matches_search_terms_with_canonical_replacement() -> None:
    clear_state = build_completion_state(
        "/cl",
        command_registry=_mechanism_registry(),
    )

    assert [item.display for item in clear_state.items] == ["/new"]
    assert clear_state.selected is not None
    assert clear_state.selected.apply("/cl") == "/new"


def test_command_completion_prioritizes_direct_matches_over_search_terms() -> None:
    state = build_completion_state(
        "/res",
        command_registry=_mechanism_registry(),
    )

    assert [item.display for item in state.items[:2]] == ["/resume", "/new"]
    assert state.selected is not None
    assert state.selected.apply("/res") == "/resume"



def test_builtin_command_completion_hides_after_completed_command_space() -> None:
    trailing_space_state = build_completion_state(
        "/compact ",
        command_registry=create_default_command_registry(),
    )
    request_state = build_completion_state(
        "/compact summarize old context",
        command_registry=create_default_command_registry(),
    )

    assert trailing_space_state.items == ()
    assert request_state.items == ()


def test_builtin_command_argument_completion_wins_over_completed_command_hide() -> None:
    state = build_completion_state(
        "/model fak",
        command_registry=create_default_command_registry(),
        model_names=("fake-model",),
    )

    assert [item.display for item in state.items] == ["fake-model"]




def test_completion_selection_wraps() -> None:
    state = build_completion_state(
        "/s",
        command_registry=_mechanism_registry(),
    )

    assert len(state.items) > 1
    assert state.select_previous().selected_index == len(state.items) - 1
    assert state.select_next().selected_index == 1


def test_model_argument_completion_preserves_existing_text() -> None:
    state = build_completion_state(
        "/model fak continue",
        command_registry=create_default_command_registry(),
        model_names=("fake-model", "other-model"),
    )

    assert [item.display for item in state.items] == ["fake-model"]
    assert state.selected is not None
    assert state.selected.apply("/model fak continue") == "/model fake-model continue"


def test_provider_argument_completion_is_not_available() -> None:
    state = build_completion_state(
        "/provider lo",
        command_registry=create_default_command_registry(),
        provider_names=("openai", "local"),
    )

    assert state.items == ()


def test_login_argument_completion_uses_available_providers() -> None:
    state = build_completion_state(
        "/login op",
        command_registry=create_default_command_registry(),
        provider_names=("openai", "openrouter", "anthropic"),
    )

    assert [item.display for item in state.items] == ["openai", "openrouter"]


def test_login_argument_completion_includes_anthropic_auth_aliases() -> None:
    state = build_completion_state(
        "/login anthropic-",
        command_registry=create_default_command_registry(),
        provider_names=("anthropic", "anthropic-api", "anthropic-subscription"),
    )

    assert [item.display for item in state.items] == [
        "anthropic-api",
        "anthropic-subscription",
    ]


def test_logout_argument_completion_uses_available_providers() -> None:
    state = build_completion_state(
        "/logout op",
        command_registry=create_default_command_registry(),
        provider_names=("openai", "openrouter", "anthropic"),
    )

    assert [item.display for item in state.items] == ["openai", "openrouter"]


def test_thinking_argument_completion_uses_available_modes() -> None:
    state = build_completion_state(
        "/thinking h",
        command_registry=create_default_command_registry(),
        thinking_levels=("low", "medium", "high", "max"),
    )

    assert state.items == ()


def test_theme_argument_completion_uses_theme_names() -> None:
    state = build_completion_state(
        "/theme tau-",
        command_registry=create_default_command_registry(),
        theme_names=("tau-dark", "tau-light", "high-contrast"),
    )

    assert [item.display for item in state.items] == ["tau-dark", "tau-light"]
    assert state.selected is not None
    assert state.selected.apply("/theme tau-") == "/theme tau-dark"


def test_resume_argument_completion_uses_session_ids() -> None:
    state = build_completion_state(
        "/resume sess",
        command_registry=create_default_command_registry(),
        session_ids=("session-1", "other"),
    )

    assert [item.display for item in state.items] == ["session-1"]
    assert state.selected is not None
    assert state.selected.apply("/resume sess") == "/resume session-1"


def test_resume_argument_completion_uses_session_options_with_descriptions() -> None:
    state = build_completion_state(
        "/resume sess",
        command_registry=create_default_command_registry(),
        session_options=(
            CompletionOption(value="session-2", description="Newer - qwen - /repo"),
            CompletionOption(value="session-1", description="Older - gpt - /repo"),
        ),
    )

    assert [item.display for item in state.items] == ["session-2", "session-1"]
    assert [item.description for item in state.items] == [
        "Newer - qwen - /repo",
        "Older - gpt - /repo",
    ]


def test_file_reference_completion_matches_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / ".hidden").write_text("secret\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("", encoding="utf-8")

    state = build_completion_state(
        "please read @app",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )

    assert [item.display for item in state.items] == ["@src/app.py"]
    assert state.selected is not None
    assert state.selected.apply("please read @app") == "please read @src/app.py"


def test_file_reference_completion_stays_off_for_slash_commands(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")

    state = build_completion_state(
        "/help @read",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )

    assert state.items == ()


def test_shell_path_completion_preserves_bang_prefix(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")

    state = build_completion_state(
        "!cat READ",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )

    assert [item.display for item in state.items] == ["README.md"]
    assert state.selected is not None
    assert state.selected.apply("!cat READ") == "!cat README.md"


def test_shell_path_completion_preserves_double_bang_prefix(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")

    state = build_completion_state(
        "!!cat READ",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )

    assert [item.display for item in state.items] == ["README.md"]
    assert state.selected is not None
    assert state.selected.apply("!!cat READ") == "!!cat README.md"


def test_shell_path_completion_matches_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    state = build_completion_state(
        "!cat src/ma",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )

    assert [item.display for item in state.items] == ["src/main.py"]
    assert state.selected is not None
    assert state.selected.apply("!cat src/ma") == "!cat src/main.py"


def test_shell_path_completion_adds_trailing_slash_for_directories(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    directory_state = build_completion_state(
        "!cat sr",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )
    child_state = build_completion_state(
        "!cat src/",
        command_registry=create_default_command_registry(),
        cwd=tmp_path,
    )

    assert [item.display for item in directory_state.items] == ["src/"]
    assert directory_state.selected is not None
    assert directory_state.selected.apply("!cat sr") == "!cat src/"
    assert [item.display for item in child_state.items] == ["src/main.py"]
