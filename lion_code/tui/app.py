"""Lion Textual TUI 主应用:面向 LionCodingSession 的前端。

与 Tau 上游 app.py(6711 行)的关系:不做整体移植,而是在已 vendor 的
组件库(TranscriptView/TuiState/TuiEventAdapter/themes/config)上实现
Lion 需要的最小应用壳,并移植 legacy TUI 的三个交互 Modal(权限确认、
Plan 审批、模型热配)。OAuth/供应商目录/扩展 UI 等 Lion 不需要的能力
不迁入;autocomplete/steering 输入等增强按迁移计划在阶段 4 接线。

事件来源有两条,职责不重叠:

- LionCodingSession.prompt() 的结构化事件流 → TuiEventAdapter → transcript
  (根 Agent 的全部对话内容);
- ui.set_sink 路由器 → 仅消费子 Agent 输出与 info/error/retry 等状态行
  (legacy 路径的打印),根 Agent 的 text/tool 打印会与核心事件重复,丢弃。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
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

from lion_code import ui
from lion_code.application.commands import CommandResult
from lion_code.application.session import LionCodingSession
from lion_code.config import save_api_config

from .config import TuiSettings, load_tui_settings, save_tui_settings
from .state import TuiState
from .adapter import TuiEventAdapter
from .themes import TuiTheme, available_tui_theme_names, get_tui_theme
from .widgets import TranscriptView


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


class UiSinkEvent(Message):
    """ui sink 事件到 Textual 消息泵的桥(仅子 Agent 与状态行)。"""

    def __init__(self, kind: str, payload: dict) -> None:
        super().__init__()
        self.kind = kind
        self.payload = payload


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
    """模型/API 配置:model + key + base url,保存即生效并持久化。

    新 TUI 只面向 Core Runtime(OpenAI-compatible)路径;切换到 Anthropic
    后端需 legacy TUI(--legacy-tui),阶段 4 Anthropic 上 Core 后放开。
    """

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
        if provider == "anthropic":
            error.update("Anthropic 后端暂需 legacy TUI(--legacy-tui 启动)")
            return
        if not model or not key:
            error.update("model 和 api key 必填")
            return
        if not base:
            error.update("OpenAI 兼容端点需要 base url")
            return
        self.dismiss(
            {
                "agent_kwargs": {
                    "model": model,
                    "api_key": key,
                    "use_openai": True,
                    "api_base": base,
                    "anthropic_base_url": None,
                },
                "config": {
                    "provider": provider,
                    "model": model,
                    "api_key": key,
                    "base_url": base,
                },
            }
        )


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
        self.state = TuiState()
        self.adapter = TuiEventAdapter(self.state)
        self._resume_on_mount = resume
        self._subagent_depth = 0
        self._status_info = ""
        keys = self.settings.keybindings
        self._bindings.bind(keys.quit, "quit_app", "quit", priority=True)
        self._bindings.bind(keys.cancel, "abort", "abort", priority=True)
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
        yield Input(placeholder="Message…   /model /clear /plan /cost /compact /theme · Esc aborts")
        yield Footer()

    async def on_mount(self) -> None:
        self._set_subtitle()
        ui.set_sink(lambda kind, payload: self.post_message(UiSinkEvent(kind, payload)))
        self.session.set_confirm_fn(self._confirm)
        self.session.set_plan_approval_fn(self._plan_approval)
        if self._resume_on_mount:
            try:
                await self.session.restore_latest()
                self._load_transcript_from_session()
            except Exception as error:
                self._notice(f"Session restore failed: {error}", role="error")
        await self._reload_sessions()
        self.query_one(Input).focus()
        if not self.session.api_configured:
            self._notice("API 未配置 — 用 /model 设置模型与密钥")
            self.call_after_refresh(self.action_model)

    async def on_unmount(self) -> None:
        ui.set_sink(None)
        await self.session.aclose()

    def _set_subtitle(self) -> None:
        self.sub_title = f"{self.session.model} | {self.session.permission_mode}"

    # ─── 会话事件流 ──────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if text.startswith("/") and not text.startswith("/skill:"):
            self._dispatch(self.session.handle_command(text))
            return
        if self.session.is_running:
            self._notice("…agent is working — Esc to abort")
            return
        self.run_worker(self._run_prompt(text), exclusive=True, group="chat")

    async def _run_prompt(self, text: str) -> None:
        transcript = self._transcript()
        transcript.follow_output()
        self._set_status(running=True)
        try:
            async for event in self.session.prompt(text):
                self.adapter.apply(event)
                transcript.update_from_state(self.state, theme=self._tui_theme)
                self._set_status(running=self.session.is_running)
        except Exception as error:
            self._notice(f"Error: {error}", role="error")
        finally:
            self._set_status(running=False)
            await self._reload_sessions()
            self.query_one(Input).focus()

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
            self._notice("未知命令 — 可用: /model /clear /plan /cost /compact /theme /quit")
            return
        if result.exit_requested:
            self.exit()
        elif result.new_session_requested:
            self.run_worker(self._new_session(), exclusive=True, group="chat")
        elif result.plan_toggle_requested:
            self.session.toggle_plan_mode()
            self._set_subtitle()
            self._notice(f"permission mode: {self.session.permission_mode}")
        elif result.cost_requested:
            usage = self.session.token_usage()
            self._notice(
                f"tokens: {usage.get('input', 0)} in / {usage.get('output', 0)} out"
            )
        elif result.compact_summary is not None:
            self.run_worker(self._compact(), exclusive=True, group="chat")
        elif result.model_picker_requested:
            self.action_model()
        elif result.theme is not None:
            self._switch_theme(result.theme)
        elif result.theme_picker_requested:
            self._notice("themes: " + ", ".join(available_tui_theme_names()))
        elif result.message:
            self._notice(result.message)

    async def _new_session(self) -> None:
        await self.session.new_session()
        self.state.clear()
        self._refresh_transcript()
        await self._reload_sessions()

    async def _compact(self) -> None:
        try:
            await self.session.compact()
            self._notice("context compacted")
        except Exception as error:
            self._notice(f"Error: {error}", role="error")

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

    # ─── ui sink 路由(子 Agent 与状态行)─────────────────────

    def on_ui_sink_event(self, event: UiSinkEvent) -> None:
        kind, p = event.kind, event.payload
        if kind == "sub_agent_start":
            self._subagent_depth += 1
            self._notice(f"┌─ Sub-agent [{p['agent_type']}]: {p['description']}")
        elif kind == "sub_agent_end":
            self._subagent_depth = max(0, self._subagent_depth - 1)
            self._notice(f"└─ Sub-agent [{p['agent_type']}] completed")
        elif kind in ("text", "tool_call", "tool_result"):
            # 根 Agent 的打印与核心事件重复,丢弃;子 Agent 输出保留为状态行。
            if self._subagent_depth > 0 and kind == "tool_call":
                self._notice(f"  {p.get('icon', '·')} {p.get('name', '')}  {p.get('summary', '')}")
        elif kind == "info":
            self._notice(f"ℹ {p['message']}")
        elif kind == "error":
            self._notice(f"Error: {p['message']}", role="error")
        elif kind == "retry":
            self._notice(f"↻ Retry {p['attempt']}/{p['max_retries']}: {p['reason']}")
        elif kind == "confirmation":
            self._notice(f"⚠ Dangerous command: {p['command']}", role="error")
        elif kind == "cost":
            self._status_info = f"{p['input']} in / {p['output']} out · ~${p['total']:.4f}"
            self._set_status(running=self.session.is_running)

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
        try:
            restored = await self.session.resume(str(name))
        except Exception as error:
            self._notice(f"Session restore failed: {error}", role="error")
            return
        if not restored:
            self._notice(f"Session {name} could not be restored.", role="error")
            return
        self._load_transcript_from_session()

    # ─── 快捷键动作 ──────────────────────────────────────────

    def action_quit_app(self) -> None:
        self.exit()

    def action_abort(self) -> None:
        if self.session.is_running:
            self.session.cancel()
            self._notice("(interrupted)")

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
        if not self._status_info:
            usage = self.session.token_usage()
            if usage.get("input") or usage.get("output"):
                self._status_info = f"{usage['input']} in / {usage['output']} out"
        if self._status_info:
            parts.append(self._status_info)
        self.query_one("#status", Static).update("   ".join(parts))


def run_tui_app(session: LionCodingSession, *, resume: bool = False) -> None:
    """新 TUI 入口:session 的组装由调用方完成,本函数只负责跑界面。"""
    LionTuiApp(session, resume=resume).run()
