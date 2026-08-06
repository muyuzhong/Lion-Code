"""Lion Textual TUI 主应用:面向 LionCodingSession 的前端。

与 Tau 上游 app.py(6711 行)的关系:不做整体移植,而是在已 vendor 的
组件库(TranscriptView/TuiState/TuiEventAdapter/themes/config)上实现
Lion 需要的最小应用壳,并移植 legacy TUI 的三个交互 Modal(权限确认、
Plan 审批、模型热配)。OAuth/供应商目录/扩展 UI 等 Lion 不需要的能力
不迁入;autocomplete/steering 输入等增强按迁移计划在阶段 4 接线。

可见反馈来自两个实例级入口,职责不重叠:

- LionCodingSession.prompt() 的结构化事件流 → TuiEventAdapter → transcript
  (根 Agent 的全部对话内容);
- LionCodingSession notice callback → 非对话的 info/error 状态行。

子 Agent 复用根调用的 tool start/end 行及 tool result,不维护第二份输出缓冲。
"""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

from rich.console import Console
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
)

from lion_code.application.commands import CommandResult
from lion_code.application.events import (
    AgentSettledEvent,
    AutoRetryStartEvent,
    LionSessionEvent,
    QueueUpdateEvent,
    SessionAgentEndEvent,
)
from lion_code.application.session import LionCodingSession
from lion_code.config import save_api_config
from lion_code.core.events import (
    AgentEndEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
)
from lion_code.core.messages import (
    AssistantMessage,
    CustomMessage,
    TextContent,
    ThinkingContent,
    UserMessage,
)
from lion_code.core.provider_events import TextDeltaEvent, ThinkingDeltaEvent

from .adapter import TuiEventAdapter
from .autocomplete import CompletionState, build_completion_state
from .config import TAU_DARK_THEME, TuiSettings, load_tui_settings, save_tui_settings
from .prompt_input import (
    COMPLETION_MAX_VISIBLE_LINES,
    PromptInput,
    text_end_location,
)
from .state import TuiState
from .terminal_notification import TerminalNotificationController
from .themes import TuiTheme, available_tui_theme_names, get_tui_theme
from .widgets import TranscriptView, render_completion_suggestions


def _textual_theme_for_tui_theme(name: str) -> Theme:
    """把 TuiTheme 映射为 Textual 原生主题(vendored 自上游 app.py)。

    widgets.py 的 DEFAULT_CSS 引用 ``$tau-markdown-*`` 等主题变量,
    必须在挂载前注册,否则样式表解析失败。
    """
    theme = get_tui_theme(name)
    return Theme(
        name=theme.name,
        primary=theme.accent,
        secondary=theme.prompt_border,
        warning=theme.markdown_bullet,
        error=theme.error,
        success=theme.success,
        accent=theme.accent,
        foreground=theme.screen_text,
        background=theme.screen_background,
        surface=theme.chrome_background,
        panel=theme.sidebar_background,
        dark=theme.dark,
        variables=_theme_css_variables(theme),
    )


def _theme_css_variables(theme: TuiTheme) -> dict[str, str]:
    """Return Textual CSS variables for a resolved TUI theme."""
    return {
        "tau-screen-background": theme.screen_background,
        "tau-screen-text": theme.screen_text,
        "tau-chrome-background": theme.chrome_background,
        "tau-chrome-text": theme.chrome_text,
        "tau-muted-text": theme.muted_text,
        "tau-sidebar-background": theme.sidebar_background,
        "tau-border": theme.border,
        "tau-transcript-background": theme.transcript_background,
        "tau-prompt-background": theme.prompt_background,
        "tau-prompt-text": theme.prompt_text,
        "tau-prompt-border": theme.prompt_border,
        "tau-autocomplete-background": theme.autocomplete_background,
        "tau-accent": theme.accent,
        "tau-tool-running": theme.role_styles["tool"].border,
        "tau-highlight-background": theme.highlight_background,
        "tau-highlight-text": theme.highlight_text,
        "tau-markdown-highlight": theme.markdown_heading,
        "tau-markdown-table-header": theme.markdown_table_header,
        "tau-markdown-table-border": theme.markdown_table_border,
        "tau-markdown-inline-code": theme.markdown_inline_code,
        "tau-markdown-code-block-background": theme.markdown_code_block_background,
        "tau-markdown-link": theme.markdown_link,
        "tau-markdown-bullet": theme.markdown_bullet,
        "footer-background": theme.chrome_background,
        "footer-foreground": theme.chrome_text,
        "footer-description-background": theme.chrome_background,
        "footer-description-foreground": theme.chrome_text,
        "footer-key-background": theme.chrome_background,
        "footer-key-foreground": theme.accent,
        "footer-item-background": theme.chrome_background,
    }


def _visible_completion_state(
    state: CompletionState,
    *,
    max_lines: int,
    width: int | None = None,
) -> CompletionState:
    """按实际渲染行裁剪补全窗口，并保证选中项可见。"""
    if not state.items or max_lines <= 0:
        return CompletionState()

    state = CompletionState(
        items=state.items,
        selected_index=min(max(state.selected_index, 0), len(state.items) - 1),
    )

    selected_line_limit = max(max_lines - 1, 1)
    start = 0
    while start < state.selected_index:
        candidate = CompletionState(
            items=state.items[start:],
            selected_index=state.selected_index - start,
        )
        if _completion_selected_render_line(candidate, width=width) < selected_line_limit:
            break
        start += 1

    end = len(state.items)
    while end > state.selected_index + 1:
        candidate = CompletionState(
            items=state.items[start:end],
            selected_index=state.selected_index - start,
        )
        if _completion_render_line_count(candidate, width=width) <= max_lines:
            break
        end -= 1

    while start < state.selected_index:
        candidate = CompletionState(
            items=state.items[start:end],
            selected_index=state.selected_index - start,
        )
        if _completion_render_line_count(candidate, width=width) <= max_lines:
            break
        start += 1

    return CompletionState(
        items=state.items[start:end],
        selected_index=state.selected_index - start,
    )


def _completion_selected_render_line(
    state: CompletionState, *, width: int | None = None
) -> int:
    """返回选中补全项所在的渲染行号。"""
    if width is not None and width > 0:
        for line_number, line in enumerate(
            _rendered_completion_lines(state, width=width)
        ):
            if line.startswith("›"):
                return line_number

    line = 0
    previous_category: str | None = None
    for index, item in enumerate(state.items):
        if item.category != previous_category:
            if index:
                line += 1
            if item.category:
                line += 1
            previous_category = item.category
        if index == state.selected_index:
            return line
        line += 1
    return line


def _completion_render_line_count(
    state: CompletionState, *, width: int | None = None
) -> int:
    """返回补全状态实际渲染的总行数。"""
    if not state.items:
        return 0
    if width is not None and width > 0:
        return len(_rendered_completion_lines(state, width=width))

    line_count = 0
    previous_category: str | None = None
    for index, item in enumerate(state.items):
        if item.category != previous_category:
            if index:
                line_count += 1
            if item.category:
                line_count += 1
            previous_category = item.category
        line_count += 1
    return line_count


def _rendered_completion_lines(
    state: CompletionState,
    *,
    width: int,
) -> tuple[str, ...]:
    """按真实表格列宽渲染补全状态并返回各行文本。"""
    output = StringIO()
    console = Console(
        file=output,
        width=width,
        force_terminal=False,
        color_system=None,
        legacy_windows=False,
    )
    console.print(
        render_completion_suggestions(
            state,
            theme=TAU_DARK_THEME,
        ),
        end="",
    )
    return tuple(output.getvalue().splitlines())


class ConfirmScreen(ModalScreen[bool]):
    """危险操作确认:y 允许,n/Esc 拒绝。"""

    BINDINGS = [
        ("y", "confirm(True)", "Yes"),
        ("n", "confirm(False)", "No"),
        ("escape", "confirm(False)", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Label(f"⚠ {self._message}"),
            Label("[y] Allow    [n/Esc] Deny", classes="dim"),
            id="dialog",
        )

    def action_confirm(self, allowed: bool) -> None:
        self.dismiss(allowed)


class PlanScreen(ModalScreen[dict]):
    """Plan 审批:与 REPL 的 1-4 选项一致。"""

    BINDINGS = [
        ("1", "pick('clear-and-execute')", "Clear & execute"),
        ("2", "pick('execute')", "Execute"),
        ("3", "pick('manual-execute')", "Manual edits"),
        ("4", "pick('keep-planning')", "Keep planning"),
        ("escape", "pick('keep-planning')", "Keep planning"),
    ]

    def __init__(self, plan: str) -> None:
        super().__init__()
        self._plan = plan

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Label("━━━ Plan for Approval ━━━"),
            Static(self._plan),
            Label(
                "[1] Clear context & execute  [2] Execute  "
                "[3] Manually approve edits  [4/Esc] Keep planning",
                classes="dim",
            ),
            id="dialog",
        )

    def action_pick(self, choice: str) -> None:
        self.dismiss({"choice": choice})


class ModelScreen(ModalScreen[dict | None]):
    """模型/API 配置:provider + model + key + base url,保存即生效并持久化。

    两种后端都走 Core Runtime;跨协议切换保留会话历史(canonical 消息
    与协议无关)。"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: dict) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        provider = "openai" if self._current["use_openai"] else "anthropic"
        yield VerticalScroll(
            Label("Model / API configuration"),
            Select(
                [("OpenAI-compatible", "openai"), ("Anthropic", "anthropic")],
                value=provider,
                allow_blank=False,
                id="provider",
            ),
            Input(value=self._current["model"], placeholder="model", id="model"),
            Input(
                value=self._current["api_key"],
                placeholder="api key",
                password=True,
                id="key",
            ),
            Input(
                value=self._current["base_url"],
                placeholder="base url(OpenAI 兼容端点必填)",
                id="base",
            ),
            Label("", id="form-error", classes="error"),
            Horizontal(
                Button("Save", variant="primary", id="save"),
                Button("Cancel", id="cancel"),
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._save()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        provider = str(self.query_one("#provider", Select).value)
        model = self.query_one("#model", Input).value.strip()
        key = self.query_one("#key", Input).value.strip()
        base = self.query_one("#base", Input).value.strip()
        error = self.query_one("#form-error", Label)
        if not model or not key:
            error.update("model 和 api key 必填")
            return
        use_openai = provider == "openai"
        if use_openai and not base:
            error.update("OpenAI 兼容端点需要 base url")
            return
        self.dismiss(
            {
                "agent_kwargs": {
                    "model": model,
                    "api_key": key,
                    "use_openai": use_openai,
                    "api_base": base if use_openai else None,
                    "anthropic_base_url": None if use_openai else (base or None),
                },
                "config": {
                    "provider": provider,
                    "model": model,
                    "api_key": key,
                    "base_url": base,
                },
            }
        )


class ModelPickerSearchInput(Input):
    """搜索框:把 picker 控制键留在弹层内(vendored 自上游,裁掉 scoped 模式)。"""

    def on_key(self, event) -> None:
        if event.key == "up":
            event.stop()
            event.prevent_default()
            self.screen.action_cursor_up()
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.screen.action_cursor_down()
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.screen.action_cancel()
        elif event.key == "ctrl+e":
            event.stop()
            event.prevent_default()
            self.screen.action_edit_config()


class ModelPickerScreen(ModalScreen[object]):
    """模型选择列表(Claude Code 式):搜索过滤、Enter 选中、Ctrl+E 编辑凭证。

    dismiss 值:ModelChoice(选中候选)| str(搜索框里的自定义模型名)|
    "__edit__"(打开凭证表单)| None(取消)。
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "accept_model", "Select"),
        ("ctrl+e", "edit_config", "Edit config"),
    ]

    def __init__(
        self,
        choices: tuple,
        *,
        current_model: str,
        provider_name: str,
    ) -> None:
        super().__init__()
        self.choices = tuple(dict.fromkeys(choices))
        self.visible_choices = self.choices
        self.current_model = current_model
        self.provider_name = provider_name
        self.search_value = ""

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Label(f"Model: {self.provider_name}"),
            ModelPickerSearchInput(placeholder="Search models…", id="model-picker-search"),
            ListView(id="model-picker-list"),
            Label("", id="model-picker-help", classes="dim"),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#model-picker-search", Input).focus()
        self._refresh_list()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "model-picker-search":
            return
        event.stop()
        self.search_value = event.value
        self._refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "model-picker-search":
            return
        event.stop()
        self.action_accept_model()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.action_accept_model()

    def action_cursor_up(self) -> None:
        self.query_one("#model-picker-list", ListView).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one("#model-picker-list", ListView).action_cursor_down()

    def action_accept_model(self) -> None:
        if self.visible_choices:
            model_list = self.query_one("#model-picker-list", ListView)
            index = model_list.index
            if index is not None:
                self.dismiss(self.visible_choices[index])
            return
        custom = self.search_value.strip()
        if custom:
            # 无匹配时把输入文本当作自定义模型名直接使用。
            self.dismiss(custom)

    def action_edit_config(self) -> None:
        self.dismiss("__edit__")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh_list(self) -> None:
        needle = self.search_value.strip().lower()
        self.visible_choices = tuple(
            choice
            for choice in self.choices
            if not needle
            or needle in choice.model.lower()
            or needle in choice.provider_name.lower()
        )
        model_list = self.query_one("#model-picker-list", ListView)
        model_list.clear()
        model_list.extend(
            ListItem(
                Label(
                    ("● " if choice.model == self.current_model else "  ")
                    + f"{choice.model}  ({choice.provider_name})",
                    markup=False,
                )
            )
            for choice in self.visible_choices
        )
        if self.visible_choices:
            try:
                model_list.index = [c.model for c in self.visible_choices].index(
                    self.current_model
                )
            except ValueError:
                model_list.index = 0
            help_text = "Enter selects · Ctrl+E edit API config · Esc closes"
        else:
            help_text = (
                "No match — Enter uses typed name as model · Ctrl+E edit API config"
            )
        self.query_one("#model-picker-help", Label).update(help_text)


class SessionPickerScreen(ModalScreen[str | None]):
    """会话选择列表:搜索过滤、Enter 恢复;dismiss 会话 id 或 None。"""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "accept", "Resume"),
    ]

    def __init__(self, sessions: list[dict], *, current_id: str | None = None) -> None:
        super().__init__()
        self.sessions = sessions
        self.visible_sessions = list(sessions)
        self.current_id = current_id
        self.search_value = ""

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Label("Resume session"),
            ModelPickerSearchInput(placeholder="Search sessions…", id="session-picker-search"),
            ListView(id="session-picker-list"),
            Label("Enter resumes · Esc closes", classes="dim"),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#session-picker-search", Input).focus()
        self._refresh_list()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "session-picker-search":
            return
        event.stop()
        self.search_value = event.value
        self._refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "session-picker-search":
            return
        event.stop()
        self.action_accept()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.action_accept()

    def action_cursor_up(self) -> None:
        self.query_one("#session-picker-list", ListView).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one("#session-picker-list", ListView).action_cursor_down()

    def action_accept(self) -> None:
        if not self.visible_sessions:
            return
        index = self.query_one("#session-picker-list", ListView).index
        if index is not None:
            self.dismiss(str(self.visible_sessions[index].get("id", "")))

    def action_cancel(self) -> None:
        self.dismiss(None)

    @staticmethod
    def _label(meta: dict) -> str:
        start = str(meta.get("startTime", ""))[:16].replace("T", " ")
        count = meta.get("messageCount", 0)
        return f"{start}  {str(meta.get('id', ''))[:8]}  ({count} msgs)"

    def _refresh_list(self) -> None:
        needle = self.search_value.strip().lower()
        self.visible_sessions = [
            meta
            for meta in self.sessions
            if not needle or needle in self._label(meta).lower()
        ]
        session_list = self.query_one("#session-picker-list", ListView)
        session_list.clear()
        session_list.extend(
            ListItem(
                Label(
                    ("● " if meta.get("id") == self.current_id else "  ")
                    + self._label(meta),
                    markup=False,
                )
            )
            for meta in self.visible_sessions
        )
        if self.visible_sessions:
            session_list.index = 0


class ThemePickerScreen(ModalScreen[str | None]):
    """主题选择列表(vendored 自上游,Claude Code 式可选列表)。"""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select_cursor", "Select"),
    ]

    def __init__(self, *, current_theme: str, theme_names: tuple[str, ...]) -> None:
        super().__init__()
        self.current_theme = current_theme
        self.theme_names = theme_names

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Label("Theme"),
            ListView(
                *[
                    ListItem(
                        Label(
                            ("● " if name == self.current_theme else "  ") + name,
                            markup=False,
                        )
                    )
                    for name in self.theme_names
                ],
                id="theme-picker-list",
            ),
            Label("Enter selects · Escape closes", classes="dim"),
            id="dialog",
        )

    def on_mount(self) -> None:
        theme_list = self.query_one("#theme-picker-list", ListView)
        try:
            theme_list.index = self.theme_names.index(self.current_theme)
        except ValueError:
            theme_list.index = 0
        theme_list.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(self.theme_names[event.index])

    def action_cursor_up(self) -> None:
        self.query_one("#theme-picker-list", ListView).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one("#theme-picker-list", ListView).action_cursor_down()

    def action_select_cursor(self) -> None:
        self.query_one("#theme-picker-list", ListView).action_select_cursor()

    def action_cancel(self) -> None:
        self.dismiss(None)


class LionTuiApp(App):
    """流式对话 + 会话侧边栏 + 确认/审批/模型三 Modal。"""

    TITLE = "Lion Code"

    CSS = """
    #sessions {
        width: 28;
        border-right: solid $primary;
        padding: 0 1;
    }
    #transcript {
        padding: 0 1;
    }
    .dim { color: $text-muted; }
    .error { color: $error; }
    #status {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #dialog {
        margin: 2 4;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
        max-height: 80%;
    }
    #autocomplete {
        height: auto;
        max-height: 17;
        background: $panel;
        padding: 0 1;
        display: none;
    }
    #prompt {
        height: auto;
        max-height: 8;
        border: tall $primary;
    }
    """

    BINDINGS = [
        ("ctrl+b", "toggle_sidebar", "sidebar"),
        ("ctrl+n", "new_session", "new session"),
        ("ctrl+m", "model", "model"),
    ]

    def __init__(
        self,
        session: LionCodingSession,
        *,
        resume: bool = False,
        settings: TuiSettings | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.settings = settings or load_tui_settings()
        self._tui_theme: TuiTheme = self.settings.resolved_theme
        # 一轮彻底归位(AgentSettled)时按设置发出终端通知(bell/desktop),让切走的
        # 用户知道本轮完成;序列写 sys.__stdout__,绕过 Textual 捕获直达终端。
        self._notification = TerminalNotificationController(
            self.settings.turn_notification
        )
        self.state = TuiState()
        self.adapter = TuiEventAdapter(self.state)
        self._resume_on_mount = resume
        self._completion_state = CompletionState()
        keys = self.settings.keybindings
        self._bindings.bind(keys.quit, "quit_app", "quit", priority=True)
        self._bindings.bind(keys.cancel, "cancel", "cancel", priority=True)
        # widgets 的 DEFAULT_CSS 引用 $tau-* 主题变量,挂载前必须注册。
        for name in available_tui_theme_names():
            self.register_theme(_textual_theme_for_tui_theme(name))
        if self.settings.theme in available_tui_theme_names():
            self.theme = self.settings.theme

    # ─── 布局与生命周期 ──────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(id="sessions")
            yield TranscriptView(id="transcript")
        yield Static("", id="status")
        yield Static("", id="autocomplete")
        yield PromptInput(id="prompt", tui_keybindings=self.settings.keybindings)
        yield Footer()

    async def on_mount(self) -> None:
        self._set_subtitle()
        self.session.set_notice_fn(self._on_session_notice)
        self.session.set_confirm_fn(self._confirm)
        self.session.set_plan_approval_fn(self._plan_approval)
        self._refresh_transcript()
        if self._resume_on_mount:
            try:
                await self.session.restore_latest()
                self._load_transcript_from_session()
            except Exception as error:
                self._notice(f"Session restore failed: {error}", role="error")
        await self._reload_sessions()
        self._prompt().focus()
        if not self.session.api_configured:
            self._notice("API 未配置 — 用 /model 设置模型与密钥")
            self.call_after_refresh(self.action_model)

    async def on_unmount(self) -> None:
        self.session.set_notice_fn(None)
        await self.session.aclose()

    def _set_subtitle(self) -> None:
        self.sub_title = f"{self.session.model} | {self.session.permission_mode}"

    # ─── 提示输入 / 补全 ─────────────────────────────────────

    def _prompt(self) -> PromptInput:
        return self.query_one("#prompt", PromptInput)

    def on_text_area_changed(self, event) -> None:
        if event.text_area.id != "prompt":
            return
        self._completion_state = self._build_completion_state(event.text_area.text)
        self._refresh_completions()

    def _build_completion_state(self, text: str) -> CompletionState:
        model_names: tuple[str, ...] = ()
        if text.startswith("/model"):
            # 仅在补 /model 参数时读本地已知模型,避免每次击键都读盘。
            model_names = tuple(
                choice.model for choice in self.session.available_model_choices
            )
        return build_completion_state(
            text,
            command_registry=self.session.command_registry,
            prompt_templates=self.session.prompt_templates,
            model_names=model_names,
            theme_names=available_tui_theme_names(),
            cwd=self.session.cwd,
            skill_names=tuple(s.name for s in self.session.skills),
        )

    def _refresh_completions(self) -> None:
        suggestions = self.query_one("#autocomplete", Static)
        suggestions.display = bool(self._completion_state.items)
        suggestions.update(
            render_completion_suggestions(
                _visible_completion_state(
                    self._completion_state,
                    max_lines=COMPLETION_MAX_VISIBLE_LINES,
                    width=max(suggestions.content_size.width or suggestions.size.width, 1),
                ),
                theme=self._tui_theme,
            )
        )
        self._sync_prompt_footer()

    def _sync_prompt_footer(self) -> None:
        if self._completion_state.items:
            mode = "completion"
        elif self.session.is_running:
            mode = "running"
        else:
            mode = "normal"
        self._prompt().set_footer_mode(mode)

    def _apply_selected_completion(self, value: str) -> str | None:
        item = self._completion_state.selected
        if item is None:
            return None
        return item.apply(value)

    def _clear_completions(self) -> None:
        self._completion_state = CompletionState()
        self._refresh_completions()

    # ─── 补全/提交动作(PromptInput 经 CompletionActionTarget 委托)──

    def action_accept_completion(self) -> None:
        if isinstance(self.screen, ThemePickerScreen):
            self.screen.action_select_cursor()
            return
        prompt = self._prompt()
        applied = self._apply_selected_completion(prompt.text)
        if applied is None:
            return
        prompt.text = applied
        prompt.move_cursor(text_end_location(applied))
        self._completion_state = self._build_completion_state(prompt.text)
        self._refresh_completions()

    def action_completion_next(self) -> None:
        if isinstance(self.screen, ThemePickerScreen):
            self.screen.action_cursor_down()
            return
        if not self._completion_state.items:
            self._prompt().action_cursor_down()
            return
        self._completion_state = self._completion_state.select_next()
        self._refresh_completions()

    def action_completion_previous(self) -> None:
        if isinstance(self.screen, ThemePickerScreen):
            self.screen.action_cursor_up()
            return
        if not self._completion_state.items:
            self._prompt().action_cursor_up()
            return
        self._completion_state = self._completion_state.select_previous()
        self._refresh_completions()

    def action_cancel(self) -> None:
        """Esc:先关补全,再取消运行。"""
        if self._completion_state.items:
            self._clear_completions()
            return
        if self.session.is_running:
            self.session.cancel()
            self._notice("(interrupted)")

    def action_edit_queued_message(self) -> bool:
        return False

    def action_open_command_palette(self) -> None:
        """把 `/` 写进空输入框即弹出全部命令补全。"""
        prompt = self._prompt()
        if not prompt.text:
            prompt.text = "/"
            prompt.move_cursor((0, 1))

    def action_open_session_picker(self) -> None:
        if not self.session.is_running:
            self.run_worker(self._open_session_picker(), group="chat")

    async def _open_session_picker(self) -> None:
        cwd = str(Path.cwd().resolve())
        metas = sorted(
            (m for m in await self.session.list_sessions() if m.get("cwd") == cwd),
            key=lambda m: m.get("startTime", ""),
            reverse=True,
        )
        if not metas:
            self._notice("没有可恢复的会话")
            return
        self.push_screen(
            SessionPickerScreen(metas, current_id=self.session.session_id),
            self._handle_session_pick,
        )

    def _handle_session_pick(self, session_id: str | None) -> None:
        if session_id:
            self.run_worker(self._resume_session(session_id), group="chat")

    async def _resume_session(self, session_id: str) -> None:
        try:
            restored = await self.session.resume(session_id)
        except Exception as error:
            self._notice(f"Session restore failed: {error}", role="error")
            return
        if not restored:
            self._notice(f"Session {session_id} could not be restored.", role="error")
            return
        self._load_transcript_from_session()
        await self._reload_sessions()

    def action_cycle_thinking(self) -> None:
        level = self.session.cycle_thinking_level()
        self._notice(f"thinking: {level}")

    def action_cycle_model(self) -> None:
        self.action_model()

    def action_toggle_tool_results(self) -> None:
        self.state.show_tool_results = not self.state.show_tool_results
        self._refresh_transcript()

    def action_toggle_thinking(self) -> None:
        self.state.show_thinking = not self.state.show_thinking
        self._refresh_transcript()

    async def action_submit_prompt(self) -> None:
        prompt = self._prompt()
        text = prompt.text_for_submission().strip()
        prompt.action_clear_prompt()
        self._clear_completions()
        if not text:
            return
        if self.session.is_running:
            if text.startswith("/"):
                self._notice("会话运行中，取消当前任务后再执行命令")
                return
            # 运行中 Enter = steer 入队。
            self.run_worker(self._queue_message(text, "steer"), group="queue")
            return
        if text.startswith("/"):
            self._dispatch(self.session.handle_command(text))
            return
        self.run_worker(self._run_prompt(text), exclusive=True, group="chat")

    async def action_submit_follow_up(self) -> None:
        prompt = self._prompt()
        text = prompt.text_for_submission().strip()
        if not text:
            return
        prompt.action_clear_prompt()
        self._clear_completions()
        if self.session.is_running:
            self.run_worker(self._queue_message(text, "follow_up"), group="queue")
        else:
            self.run_worker(self._run_prompt(text), exclusive=True, group="chat")

    async def _queue_message(self, text: str, behavior: str) -> None:
        async for event in self.session.prompt(text, streaming_behavior=behavior):  # type: ignore[arg-type]
            self.adapter.apply(event)
        self._notice(f"queued ({behavior}): {text[:60]}")

    # ─── 会话事件流 ──────────────────────────────────────────

    async def _run_prompt(self, text: str) -> None:
        transcript = self._transcript()
        transcript.follow_output()
        self._set_status(running=True)
        try:
            async for event in self.session.prompt(text):
                previous_item_count = len(self.state.items)
                self.adapter.apply(event)
                await self._apply_streaming_transcript_event(
                    event,
                    previous_item_count=previous_item_count,
                )
                self._set_status(running=self.session.is_running)
                if isinstance(event, AgentSettledEvent):
                    self._notification.notify_turn_finished()
        except Exception as error:
            self._notice(f"Error: {error}", role="error")
        finally:
            self._set_status(running=False)
            await self._reload_sessions()
            self._prompt().focus()

    async def _apply_streaming_transcript_event(
        self,
        event: LionSessionEvent,
        *,
        previous_item_count: int,
    ) -> None:
        """把单个会话事件增量投影到已挂载 transcript。"""
        transcript = self._transcript()
        theme = self._tui_theme

        if isinstance(event, AgentStartEvent | MessageStartEvent | QueueUpdateEvent):
            return
        if isinstance(event, AgentEndEvent | SessionAgentEndEvent):
            await transcript.finish_assistant_message()
            return
        if isinstance(event, MessageUpdateEvent):
            nested = event.assistant_message_event
            if isinstance(nested, TextDeltaEvent):
                await transcript.append_assistant_delta(nested.delta, theme=theme)
            elif isinstance(nested, ThinkingDeltaEvent):
                await transcript.append_thinking_delta(
                    nested.delta,
                    theme=theme,
                    show_thinking=self.state.show_thinking,
                )
            return
        if isinstance(event, MessageEndEvent):
            if isinstance(event.message, (UserMessage, CustomMessage)):
                for item in self.state.items[previous_item_count:]:
                    expanded = self.state.show_tool_results or item.always_show_tool_result
                    await transcript.append_item(
                        item,
                        theme=theme,
                        show_tool_results=expanded,
                        custom_markup=(
                            self.state.resolve_custom_markup(
                                item,
                                expanded=self.state.show_tool_results,
                            )
                            if item.role == "custom"
                            else None
                        ),
                    )
                return
            if isinstance(event.message, AssistantMessage):
                if event.message.stop_reason in {"error", "aborted"}:
                    # 终止错误可能同时投影部分回复和错误行；只在该边界全量校准一次。
                    self._refresh_transcript()
                    return
                visible_blocks = [
                    block
                    for block in event.message.content
                    if (
                        (isinstance(block, TextContent) and bool(block.text))
                        or (isinstance(block, ThinkingContent) and bool(block.thinking))
                    )
                ]
                canonical_items = (
                    self.state.items[-len(visible_blocks) :] if visible_blocks else []
                )
                if (
                    any(isinstance(block, ThinkingContent) for block in visible_blocks)
                    or len(visible_blocks) > 1
                ):
                    await transcript.finish_structured_assistant_message(
                        canonical_items,
                        theme=theme,
                        show_thinking=self.state.show_thinking,
                    )
                else:
                    canonical_item = canonical_items[-1] if canonical_items else None
                    await transcript.finish_assistant_message(
                        event.message.text,
                        item=canonical_item,
                    )
                return
            return
        if isinstance(event, ToolExecutionStartEvent):
            await transcript.finish_assistant_message()
            item = self.state.items[-1]
            await transcript.append_item(
                item,
                theme=theme,
                show_tool_results=self.state.show_tool_results,
                invocation=self.state.resolve_tool_invocation(item),
            )
            return
        if isinstance(event, ToolExecutionUpdateEvent):
            await transcript.finish_assistant_message()
            updated_item = self.state.find_tool_item(event.tool_call_id)
            if updated_item is not None:
                expanded = (
                    self.state.show_tool_results
                    or updated_item.always_show_tool_result
                )
                await transcript.update_item(
                    updated_item,
                    theme=theme,
                    show_tool_results=expanded,
                    invocation=self.state.resolve_tool_invocation(updated_item),
                    result_markup=self.state.resolve_tool_result(
                        updated_item,
                        expanded=expanded,
                    ),
                )
            return
        if isinstance(event, ToolExecutionEndEvent):
            updated_item = self.state.find_tool_item(event.tool_call_id)
            if updated_item is not None:
                expanded = (
                    self.state.show_tool_results
                    or updated_item.always_show_tool_result
                )
                await transcript.update_item(
                    updated_item,
                    theme=theme,
                    show_tool_results=expanded,
                    invocation=self.state.resolve_tool_invocation(updated_item),
                    result_markup=self.state.resolve_tool_result(
                        updated_item,
                        expanded=expanded,
                    ),
                )
            return
        if isinstance(event, AutoRetryStartEvent):
            await transcript.finish_assistant_message()
            if len(self.state.items) > previous_item_count:
                await transcript.append_item(
                    self.state.items[-1],
                    theme=theme,
                    show_tool_results=self.state.show_tool_results,
                )

    def _refresh_transcript(self) -> None:
        self._transcript().update_from_state(self.state, theme=self._tui_theme)

    def _load_transcript_from_session(self) -> None:
        self.state.clear()
        self.state.load_messages(self.session.messages)
        self._refresh_transcript()
        self._set_subtitle()

    # ─── 命令分发(CommandResult 意图)────────────────────────

    def _dispatch(self, result: CommandResult) -> None:
        if not result.handled:
            self._notice(
                "未知命令 — 可用: /task /session-memory /handoff /dream "
                "/model /clear /plan /cost /compact /theme /thinking /quit /skills"
            )
            return
        if result.exit_requested:
            self.exit()
        elif result.new_session_requested:
            self.run_worker(self._new_session(), exclusive=True, group="chat")
        elif result.plan_toggle_requested:
            self.session.toggle_plan_mode()
            self._set_subtitle()
        elif result.cost_requested:
            usage = self.session.token_usage()
            self._notice(
                f"tokens: {usage.get('input', 0)} in / {usage.get('output', 0)} out"
            )
        elif result.compact_summary is not None:
            self.run_worker(self._compact(), exclusive=True, group="chat")
        elif result.skill_prompt is not None:
            self.run_worker(
                self._run_prompt(result.skill_prompt), exclusive=True, group="chat"
            )
        elif result.skills_list_requested:
            self._show_skills_list()
        elif (
            result.task_action is not None
            or result.session_memory_requested
            or result.handoff_requested
            or result.dream_requested
        ):
            self.run_worker(
                self._execute_session_memory_command(result),
                exclusive=True,
                group="chat",
            )
        elif result.model_picker_requested:
            self.action_model()
        elif result.resume_session_id is not None:
            self.run_worker(self._resume_session(result.resume_session_id), group="chat")
        elif result.resume_picker_requested:
            self.run_worker(self._open_session_picker(), group="chat")
        elif result.theme is not None:
            self._switch_theme(result.theme)
        elif result.theme_picker_requested:
            self.push_screen(
                ThemePickerScreen(
                    current_theme=self.settings.theme,
                    theme_names=available_tui_theme_names(),
                ),
                lambda name: self._switch_theme(name) if name else None,
            )
        elif result.thinking_level is not None:
            self._notice(result.message or f"thinking: {result.thinking_level}")
        elif result.message:
            self._notice(result.message)
        self._set_subtitle()

    async def _new_session(self) -> None:
        await self.session.new_session()
        self.state.clear()
        self._refresh_transcript()
        await self._reload_sessions()

    async def _compact(self) -> None:
        try:
            await self.session.compact()
        except Exception as error:
            self._notice(f"Error: {error}", role="error")

    def _show_skills_list(self) -> None:
        """显示可用 Skill 列表。"""

        skills = self.session.skills
        if not skills:
            self._notice("No skills found. Add skills to .claude/skills/<name>/SKILL.md")
            return
        lines = [f"{len(skills)} skills:"]
        for skill in skills:
            tag = f"/{skill.name}"
            desc = skill.description or ""
            lines.append(f"  {tag} - {desc}")
        self._notice("\n".join(lines))

    async def _execute_session_memory_command(self, result: CommandResult) -> None:
        """在应用会话层执行共享的短期记忆命令意图。"""

        try:
            message = await self.session.execute_session_memory_command(result)
        # 前端必须把异步命令失败显示为状态行，不能让 Worker 静默退出。
        except Exception as error:  # noqa: BLE001
            self._notice(f"Error: {error}", role="error")
            return
        if message:
            self._notice(message)

    def _switch_theme(self, name: str) -> None:
        try:
            self._tui_theme = get_tui_theme(name)
        except KeyError:
            self._notice(f"unknown theme: {name} — " + ", ".join(available_tui_theme_names()))
            return
        self.settings = replace(self.settings, theme=name)
        save_tui_settings(self.settings)
        if name in available_tui_theme_names():
            self.theme = name
        self._refresh_transcript()
        self._notice(f"theme: {name}")

    # ─── 会话侧边栏 ──────────────────────────────────────────

    async def _reload_sessions(self) -> None:
        lv = self.query_one("#sessions", ListView)
        await lv.clear()
        lv.append(ListItem(Label("＋ New session"), name="__new__"))
        cwd = str(Path.cwd().resolve())
        metas = sorted(
            (m for m in await self.session.list_sessions() if m.get("cwd") == cwd),
            key=lambda m: m.get("startTime", ""),
            reverse=True,
        )
        for m in metas:
            sid = str(m.get("id", ""))
            label = f"{str(m.get('startTime', ''))[:16]}  {sid[:8]}"
            lv.append(ListItem(Label(label), name=sid))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self.session.is_running:
            self._notice("…agent is working — Esc to abort")
            return
        name = event.item.name
        if name == "__new__":
            await self._new_session()
            return
        await self._resume_session(str(name))

    # ─── 快捷键动作 ──────────────────────────────────────────

    def action_quit_app(self) -> None:
        self.exit()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sessions")
        sidebar.display = not sidebar.display

    async def action_new_session(self) -> None:
        if not self.session.is_running:
            await self._new_session()

    def action_model(self) -> None:
        if self.session.is_running:
            self._notice("…agent is working — Esc to abort")
            return
        if not self.session.api_configured:
            # 首跑没有凭证,直接进表单;配置过之后一律列表 picker。
            self._open_model_form()
            return
        self.push_screen(
            ModelPickerScreen(
                self.session.available_model_choices,
                current_model=self.session.model,
                provider_name=self.session.provider_name,
            ),
            self._handle_model_pick,
        )

    def _handle_model_pick(self, result: object) -> None:
        if result is None:
            return
        if result == "__edit__":
            self._open_model_form()
            return
        model = result if isinstance(result, str) else result.model
        self.session.set_model(model)
        self._set_subtitle()
        self._notice(f"Model set: {model}")

    def _open_model_form(self) -> None:
        self.push_screen(
            ModelScreen(self.session.get_provider_config()), self._apply_model_config
        )

    def _apply_model_config(self, result: dict | None) -> None:
        if not result:
            return
        self.session.configure_provider(**result["agent_kwargs"])
        save_api_config(**result["config"])
        self._set_subtitle()
        cfg = result["config"]
        self._notice(f"Model set: {cfg['model']} ({cfg['provider']})")

    # ─── 交互注入(Agent 回调)───────────────────────────────

    async def _confirm(self, message: str) -> bool:
        return await self.push_screen_wait(ConfirmScreen(message))

    async def _plan_approval(self, plan: str) -> dict:
        return await self.push_screen_wait(PlanScreen(plan))

    def _on_session_notice(self, text: str, role: str) -> None:
        rendered = text if role == "info" else f"Error: {text}"
        # Agent 的同步状态回调可能发生在 clear/restore 的状态替换中；排到当前
        # Textual 消息之后，避免通知先被 reconcile 清除，也保证每次只渲染一次。
        self.call_later(
            self._notice,
            rendered,
            role="error" if role == "error" else "status",
        )

    # ─── 渲染辅助 ────────────────────────────────────────────

    def _transcript(self) -> TranscriptView:
        return self.query_one("#transcript", TranscriptView)

    def _notice(self, text: str, *, role: str = "status") -> None:
        self.state.add_item(role, text)  # type: ignore[arg-type]
        self._refresh_transcript()

    def _set_status(self, *, running: bool) -> None:
        parts = []
        if running:
            parts.append("⠋ Thinking…")
        usage = self.session.token_usage()
        if usage.get("input") or usage.get("output"):
            parts.append(f"{usage['input']} in / {usage['output']} out")
        self.query_one("#status", Static).update("   ".join(parts))
        self._sync_prompt_footer()


def run_tui_app(session: LionCodingSession, *, resume: bool = False) -> None:
    """新 TUI 入口:session 的组装由调用方完成,本函数只负责跑界面。"""
    LionTuiApp(session, resume=resume).run()
