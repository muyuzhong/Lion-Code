"""Textual TUI：Agent 核心的替代前端。

与核心完全分离：通过 ui.set_sink 接管 Agent 的全部输出（流式文本、工具
调用、状态事件），通过 set_confirm_fn / set_plan_approval_fn 注入交互；
不修改、不感知 Agent 内部实现。

快捷键与主题由 ~/.lion-code/tui.json 配置，例如：
{
  "theme": "nord",
  "keys": {"quit": "ctrl+q", "abort": "escape",
           "toggle_sidebar": "ctrl+b", "new_session": "ctrl+n"}
}
"""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Select, Static

from . import ui
from .agent import Agent
from .config import save_api_config
from .session import list_sessions, load_session

CONFIG_PATH = Path.home() / ".lion-code" / "tui.json"

DEFAULT_CONFIG = {
    "theme": "textual-dark",
    "keys": {
        "quit": "ctrl+q",
        "abort": "escape",
        "toggle_sidebar": "ctrl+b",
        "new_session": "ctrl+n",
        "model": "ctrl+m",
    },
}


def load_config() -> dict:
    """读取用户配置并与默认值合并；文件缺失或损坏时静默回退默认。"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    if isinstance(user, dict):
        if isinstance(user.get("theme"), str):
            cfg["theme"] = user["theme"]
        if isinstance(user.get("keys"), dict):
            cfg["keys"].update({k: v for k, v in user["keys"].items() if isinstance(v, str)})
    return cfg


class AgentEvent(Message):
    """ui sink 事件到 Textual 消息泵的桥。"""

    def __init__(self, kind: str, payload: dict) -> None:
        super().__init__()
        self.kind = kind
        self.payload = payload


class ConfirmScreen(ModalScreen[bool]):
    """危险操作确认：y 允许，n/Esc 拒绝。"""

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
    """Plan 审批：与 REPL 的 1-4 选项一致；选 4 的修改意见直接在下一条消息里说。"""

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
    """模型/API 配置：provider + model + key + base url，保存即生效并持久化。"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent

    def compose(self) -> ComposeResult:
        current = self._agent.get_api_config()
        provider = "openai" if current["use_openai"] else "anthropic"
        yield VerticalScroll(
            Label("Model / API configuration"),
            Select(
                [("Anthropic", "anthropic"), ("OpenAI-compatible", "openai")],
                value=provider,
                allow_blank=False,
                id="provider",
            ),
            Input(value=current["model"], placeholder="model", id="model"),
            Input(value=current["api_key"], placeholder="api key", password=True, id="key"),
            Input(value=current["base_url"], placeholder="base url（OpenAI 兼容端点必填）", id="base"),
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
        if not model or not key:
            self.query_one("#form-error", Label).update("model 和 api key 必填")
            return
        if provider == "openai" and not base:
            self.query_one("#form-error", Label).update("OpenAI 兼容端点需要 base url")
            return
        self.dismiss({
            "agent_kwargs": {
                "model": model,
                "api_key": key,
                "use_openai": provider == "openai",
                "api_base": base or None,
                "anthropic_base_url": None if provider == "openai" else (base or None),
            },
            "config": {
                "provider": provider,
                "model": model,
                "api_key": key,
                "base_url": base,
            },
        })


class LionTUI(App):
    """最小可观测 TUI：流式对话 + 会话侧边栏 + 确认/审批弹窗。"""

    TITLE = "Lion Code"

    CSS = """
    #sessions {
        width: 28;
        border-right: solid $primary;
        padding: 0 1;
    }
    #chat {
        padding: 0 2;
    }
    #chat Static {
        margin-bottom: 1;
    }
    .user { color: $success; text-style: bold; }
    .tool { color: $warning; }
    .dim { color: $text-muted; }
    .info { color: $accent; }
    .error { color: $error; }
    .sub { color: $secondary; }
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

    def __init__(self, agent: Agent, config: dict | None = None) -> None:
        super().__init__()
        self.agent = agent
        self.config = config or load_config()
        self._processing = False
        self._stream_widget: Static | None = None
        self._stream_text = ""
        self._spinner_on = False
        self._spinner_label = "Thinking"
        self._status_info = ""
        for action, key in self.config["keys"].items():
            self._bindings.bind(key, action, action.replace("_", " "), priority=True)
        try:
            self.theme = self.config["theme"]
        except Exception:
            pass  # 未知主题名时保留默认主题。

    # ─── 布局与生命周期 ──────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(id="sessions")
            yield VerticalScroll(id="chat")
        yield Static("", id="status")
        yield Input(placeholder="Message…   /model /clear /plan /cost /compact · Esc aborts")
        yield Footer()

    def on_mount(self) -> None:
        self._set_subtitle()
        ui.set_sink(lambda kind, payload: self.post_message(AgentEvent(kind, payload)))
        self.agent.set_confirm_fn(self._confirm)
        self.agent.set_plan_approval_fn(self._plan_approval)
        self._reload_sessions()
        self.query_one(Input).focus()
        if not self.agent.api_configured:
            self._add("ℹ API 未配置 — 用 /model 设置模型与密钥", "info")
            self.call_after_refresh(self.action_model)

    def _set_subtitle(self) -> None:
        self.sub_title = f"{self.agent.model} | {self.agent.permission_mode}"

    async def on_unmount(self) -> None:
        ui.set_sink(None)
        await self.agent.close()

    # ─── Agent 事件渲染 ──────────────────────────────────────

    def on_agent_event(self, event: AgentEvent) -> None:
        kind = event.kind
        p = event.payload
        if kind == "text":
            self._stream_text += p["text"]
            if self._stream_widget is None:
                self._stream_widget = Static("", classes="assistant", markup=False)
                self._chat().mount(self._stream_widget)
            self._stream_widget.update(self._stream_text)
            self._scroll_end()
        elif kind == "tool_call":
            self._end_stream()
            self._add(f"{p['icon']} {p['name']}  {p['summary']}", "tool")
        elif kind == "tool_result":
            self._add(p["text"], "dim")
        elif kind == "info":
            self._add(f"ℹ {p['message']}", "info")
        elif kind == "error":
            self._add(f"Error: {p['message']}", "error")
        elif kind == "retry":
            self._add(f"↻ Retry {p['attempt']}/{p['max_retries']}: {p['reason']}", "tool")
        elif kind == "confirmation":
            self._add(f"⚠ Dangerous command: {p['command']}", "error")
        elif kind == "sub_agent_start":
            self._end_stream()
            self._add(f"┌─ Sub-agent [{p['agent_type']}]: {p['description']}", "sub")
        elif kind == "sub_agent_end":
            self._add(f"└─ Sub-agent [{p['agent_type']}] completed", "sub")
        elif kind == "cost":
            self._status_info = (
                f"{p['input']} in / {p['output']} out · ~${p['total']:.4f}"
            )
            self._set_status()
        elif kind == "spinner":
            self._spinner_on = p["on"]
            self._spinner_label = p.get("label", "Thinking")
            self._set_status()
        elif kind == "divider":
            self._end_stream()
            t = self.agent.get_token_usage()
            self._status_info = f"{t['input']} in / {t['output']} out"
            self._set_status()
        elif kind == "chat_done":
            self._processing = False
            self._spinner_on = False
            self._set_status()
            self.query_one(Input).focus()

    # ─── 输入与命令 ──────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if self._processing:
            self._add("…agent is working — Esc to abort", "dim")
            return
        if text.startswith("/"):
            await self._handle_command(text)
            return
        self._end_stream()
        self._add(f"> {text}", "user")
        self._processing = True
        self.run_worker(self._chat_once(text), exclusive=True, group="chat")

    async def _chat_once(self, text: str) -> None:
        try:
            await self.agent.chat(text)
        except Exception as e:
            self.post_message(AgentEvent("error", {"message": str(e)}))
        finally:
            self.post_message(AgentEvent("chat_done", {}))

    async def _handle_command(self, text: str) -> None:
        cmd = text.split(maxsplit=1)[0]
        if cmd == "/clear":
            self.agent.clear_history()
            self._clear_chat()
        elif cmd == "/plan":
            self.agent.toggle_plan_mode()
        elif cmd == "/cost":
            self.agent.show_cost()
        elif cmd == "/compact":
            try:
                await self.agent.compact()
            except Exception as e:
                self._add(f"Error: {e}", "error")
        elif cmd == "/model":
            self.action_model()
        elif cmd in ("/exit", "/quit"):
            self.exit()
        else:
            self._add(f"ℹ {cmd} not supported in TUI yet — use the REPL", "info")

    # ─── 会话侧边栏 ──────────────────────────────────────────

    def _reload_sessions(self) -> None:
        lv = self.query_one("#sessions", ListView)
        lv.clear()
        lv.append(ListItem(Label("＋ New session"), name="__new__"))
        cwd = str(Path.cwd().resolve())
        metas = sorted(
            (m for m in list_sessions() if m.get("cwd") == cwd),
            key=lambda m: m.get("startTime", ""),
            reverse=True,
        )
        for m in metas:
            sid = str(m.get("id", ""))
            label = f"{str(m.get('startTime', ''))[:16]}  {sid[:8]}"
            lv.append(ListItem(Label(label), name=sid))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._processing:
            self._add("…agent is working — Esc to abort", "dim")
            return
        name = event.item.name
        if name == "__new__":
            self.agent.clear_history()
            self._clear_chat()
            return
        session = load_session(str(name))
        if not session:
            return
        self._clear_chat()
        self.agent.restore_session({
            "anthropicMessages": session.get("anthropicMessages"),
            "openaiMessages": session.get("openaiMessages"),
        })
        # restore_session 的 print_info 会经 sink 落到聊天区。

    # ─── 快捷键动作 ──────────────────────────────────────────

    def action_abort(self) -> None:
        if self._processing:
            self.agent.abort()
            self._add("(interrupted)", "dim")

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sessions")
        sidebar.display = not sidebar.display

    def action_new_session(self) -> None:
        if self._processing:
            return
        self.agent.clear_history()
        self._clear_chat()

    def action_model(self) -> None:
        if self._processing:
            self._add("…agent is working — Esc to abort", "dim")
            return
        self.push_screen(ModelScreen(self.agent), self._apply_model_config)

    def _apply_model_config(self, result: dict | None) -> None:
        if not result:
            return
        self.agent.configure_api(**result["agent_kwargs"])
        save_api_config(**result["config"])
        self._set_subtitle()
        cfg = result["config"]
        self._add(f"ℹ Model set: {cfg['model']} ({cfg['provider']})", "info")

    # ─── 交互注入（Agent 回调）───────────────────────────────

    async def _confirm(self, message: str) -> bool:
        return await self.push_screen_wait(ConfirmScreen(message))

    async def _plan_approval(self, plan: str) -> dict:
        return await self.push_screen_wait(PlanScreen(plan))

    # ─── 渲染辅助 ────────────────────────────────────────────

    def _chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    def _add(self, text: str, classes: str) -> None:
        self._chat().mount(Static(text, classes=classes, markup=False))
        self._scroll_end()

    def _end_stream(self) -> None:
        self._stream_widget = None
        self._stream_text = ""

    def _scroll_end(self) -> None:
        self._chat().scroll_end(animate=False)

    def _set_status(self) -> None:
        parts = []
        if self._spinner_on:
            parts.append(f"⠋ {self._spinner_label}…")
        if self._status_info:
            parts.append(self._status_info)
        self.query_one("#status", Static).update("   ".join(parts))

    def _clear_chat(self) -> None:
        self._end_stream()
        self._chat().remove_children()


def run_tui(agent: Agent) -> None:
    """TUI 入口：agent 的构建与 CLI 完全一致，本函数只负责跑界面。"""
    LionTUI(agent).run()
