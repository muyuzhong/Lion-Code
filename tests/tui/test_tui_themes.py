from pathlib import Path
from typing import Any

import pytest

from lion_code.tui.config import TuiSettings
from lion_code.tui.themes import (
    BUILTIN_TUI_THEME_NAMES,
    TAU_DARK_THEME,
    TAU_LIGHT_THEME,
    THEME_COLOR_FIELDS,
    TRANSCRIPT_ROLES,
    TuiThemeError,
    available_tui_theme_names,
    get_tui_theme,
    parse_tui_theme_json,
)


def _theme_data(name: str = "midnight", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        "colors": {field_name: "#101010" for field_name in THEME_COLOR_FIELDS},
        "roles": {role: {"border": "#101010", "body": "#e0e0e0"} for role in TRANSCRIPT_ROLES},
    }
    data.update(overrides)
    return data

def test_parse_theme_resolves_vars_inside_style_strings() -> None:
    data = _theme_data(vars={"base": "#1e1e2e", "teal": "#94e2d5"})
    data["colors"]["screen_background"] = "base"
    data["colors"]["completion_selected"] = "bold base on teal"
    data["roles"]["user"] = {"border": "teal", "body": "#cdd6f4 on base"}

    theme = parse_tui_theme_json(data)

    assert theme.name == "midnight"
    assert theme.screen_background == "#1e1e2e"
    assert theme.completion_selected == "bold #1e1e2e on #94e2d5"
    assert theme.role_styles["user"].border == "#94e2d5"
    assert theme.role_styles["user"].body == "#cdd6f4 on #1e1e2e"

def test_parse_theme_defaults_dark_and_syntax_theme_from_background() -> None:
    dark_data = _theme_data()
    dark_data["colors"]["screen_background"] = "#1e1e2e"
    light_data = _theme_data(name="daylight")
    light_data["colors"]["screen_background"] = "#eff1f5"

    dark_theme = parse_tui_theme_json(dark_data)
    light_theme = parse_tui_theme_json(light_data)

    assert dark_theme.dark is True
    assert dark_theme.syntax_theme == "ansi_dark"
    assert light_theme.dark is False
    assert light_theme.syntax_theme == "ansi_light"

def test_parse_theme_honors_explicit_dark_and_syntax_theme() -> None:
    data = _theme_data(dark=False, syntax_theme="ansi_light")
    data["colors"]["screen_background"] = "#000000"

    theme = parse_tui_theme_json(data)

    assert theme.dark is False
    assert theme.syntax_theme == "ansi_light"

def test_parse_theme_rejects_unparseable_colors_and_styles() -> None:
    data = _theme_data()
    data["colors"]["screen_background"] = "not-a-color"
    data["colors"]["accent"] = "bold #ffffff on #000000"
    data["colors"]["completion_selected"] = "bold nope on #000000"
    data["roles"]["user"] = {"border": "#12345", "body": "shiny on #000000"}

    with pytest.raises(TuiThemeError) as exc_info:
        parse_tui_theme_json(data)

    message = str(exc_info.value)
    assert "colors.screen_background" in message
    assert "colors.accent" in message
    assert "colors.completion_selected" in message
    assert "roles.user.border" in message
    assert "roles.user.body" in message

@pytest.mark.parametrize("color", ["bright_red", "color(123)", "grey50", "default"])
def test_parse_theme_rejects_rich_only_colors_in_textual_fields(color: str) -> None:
    # Rich's parser accepts these, but Textual's does not; they would crash
    # the TUI when the theme's CSS variables are applied.
    data = _theme_data()
    data["colors"]["accent"] = color

    with pytest.raises(TuiThemeError, match="colors.accent"):
        parse_tui_theme_json(data)

@pytest.mark.parametrize("color", ["tomato", "ansi_red", "#ff000080"])
def test_parse_theme_rejects_textual_only_colors_in_shared_fields(color: str) -> None:
    # Shared fields also render through Rich, so colors must satisfy both
    # parsers; Textual-only syntax is rejected just like Rich-only syntax.
    data = _theme_data()
    data["colors"]["accent"] = color

    with pytest.raises(TuiThemeError, match="colors.accent"):
        parse_tui_theme_json(data)

def test_parse_theme_allows_rich_only_colors_in_rich_only_fields() -> None:
    data = _theme_data()
    data["colors"]["tool_success_text"] = "bright_green"
    data["colors"]["tool_error_text"] = "color(160)"
    data["colors"]["completion_selected"] = "bold grey50 on #101010"

    theme = parse_tui_theme_json(data)

    assert theme.tool_success_text == "bright_green"
    assert theme.completion_selected == "bold grey50 on #101010"

@pytest.mark.parametrize("body", ["bright_white on #101010", "#e0e0e0 on grey11", "default"])
def test_parse_theme_rejects_rich_only_colors_in_role_bodies(body: str) -> None:
    # Body foreground/background colors feed Textual's styles.color and
    # styles.background, so they must parse under both libraries.
    data = _theme_data()
    data["roles"]["user"] = {"border": "#101010", "body": body}

    with pytest.raises(TuiThemeError, match="roles.user.body"):
        parse_tui_theme_json(data)

def test_parse_theme_rejects_rich_only_colors_in_role_borders() -> None:
    # Role borders feed Textual's styles.border_left as well as Rich tables.
    data = _theme_data()
    data["roles"]["user"] = {"border": "bright_red", "body": "#e0e0e0"}

    with pytest.raises(TuiThemeError, match="roles.user.border"):
        parse_tui_theme_json(data)

def test_parse_theme_rejects_rich_only_var_resolved_into_textual_field() -> None:
    data = _theme_data(vars={"base": "grey50"})
    data["colors"]["screen_background"] = "base"

    with pytest.raises(TuiThemeError, match="colors.screen_background"):
        parse_tui_theme_json(data)

def test_parse_theme_reports_all_problems_at_once() -> None:
    data = _theme_data()
    del data["colors"]["accent"]
    del data["colors"]["border"]
    del data["roles"]["thinking"]
    data["colors"]["not_a_field"] = "#000000"

    with pytest.raises(TuiThemeError) as exc_info:
        parse_tui_theme_json(data)

    message = str(exc_info.value)
    assert "accent" in message
    assert "border" in message
    assert "thinking" in message
    assert "not_a_field" in message

def test_parse_theme_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(TuiThemeError, match="palette"):
        parse_tui_theme_json(_theme_data(palette={}))

def test_parse_theme_allows_schema_field() -> None:
    data = _theme_data()
    data["$schema"] = "./theme-schema.json"

    assert parse_tui_theme_json(data).name == "midnight"

def test_parse_theme_rejects_var_names_that_collide_with_rich_keywords() -> None:
    with pytest.raises(TuiThemeError, match="on"):
        parse_tui_theme_json(_theme_data(vars={"on": "#101010"}))

def test_parse_theme_rejects_var_values_with_whitespace() -> None:
    with pytest.raises(TuiThemeError, match="base"):
        parse_tui_theme_json(_theme_data(vars={"base": "#101010 on #202020"}))

def test_parse_theme_rejects_var_values_that_are_not_colors() -> None:
    # A style keyword smuggled through a var would corrupt style strings.
    with pytest.raises(TuiThemeError, match="base"):
        parse_tui_theme_json(_theme_data(vars={"base": "bold"}))

def test_transcript_roles_are_shared_with_tui_state() -> None:
    from lion_code.tui.state import ChatItemRole
    from lion_code.tui.themes import TranscriptRole

    assert ChatItemRole is TranscriptRole

def test_parse_theme_rejects_invalid_names() -> None:
    with pytest.raises(TuiThemeError, match="name"):
        parse_tui_theme_json(_theme_data(name=""))
    with pytest.raises(TuiThemeError, match="name"):
        parse_tui_theme_json(_theme_data(name="light/dark"))

def test_parse_theme_rejects_unknown_syntax_theme() -> None:
    with pytest.raises(TuiThemeError, match="syntax_theme"):
        parse_tui_theme_json(_theme_data(syntax_theme="not-a-pygments-style"))

def test_parse_theme_rejects_non_object_payload() -> None:
    with pytest.raises(TuiThemeError, match="object"):
        parse_tui_theme_json(["not", "a", "theme"])

def test_builtin_themes_are_loaded_from_packaged_json() -> None:
    assert BUILTIN_TUI_THEME_NAMES == ("tau-dark", "tau-light", "high-contrast")
    assert TAU_DARK_THEME.dark is True
    assert TAU_LIGHT_THEME.dark is False
    assert get_tui_theme("tau-dark").screen_background == "#000000"
    assert get_tui_theme("high-contrast").prompt_border == "#00ff66"
    assert get_tui_theme("tau-light").syntax_theme == "ansi_light"

def test_resolved_theme_falls_back_to_tau_dark_for_unknown_names() -> None:
    settings = TuiSettings(theme="missing-theme")

    assert settings.resolved_theme == TAU_DARK_THEME

