"""TUI 与 ui sink 的最小验证：事件捕获、配置合并、App 冒烟。"""

from __future__ import annotations

import json

import pytest
from textual.widgets import Button, Input

from lion_code import ui


@pytest.fixture
def captured():
    events: list[tuple[str, dict]] = []
    ui.set_sink(lambda kind, payload: events.append((kind, payload)))
    yield events
    ui.set_sink(None)


def test_sink_captures_text_and_tool_events(captured):
    ui.print_assistant_text("hello")
    ui.print_tool_call("read_file", {"file_path": "a.py"})
    ui.print_tool_result("read_file", "x" * 600)
    assert captured[0] == ("text", {"text": "hello"})
    assert captured[1][0] == "tool_call"
    assert captured[1][1]["name"] == "read_file"
    assert captured[1][1]["summary"] == "a.py"
    assert captured[2][0] == "tool_result"
    assert "600 chars total" in captured[2][1]["text"]


def test_sink_captures_status_events(captured):
    ui.print_info("note")
    ui.print_error("bad")
    ui.print_cost(1000, 500)
    ui.start_spinner()
    ui.stop_spinner()
    ui.print_divider()
    ui.print_sub_agent_start("explore", "find stuff")
    ui.print_sub_agent_end("explore", "find stuff")
    kinds = [k for k, _ in captured]
    assert kinds == [
        "info", "error", "cost", "spinner", "spinner",
        "divider", "sub_agent_start", "sub_agent_end",
    ]
    assert captured[2][1]["input"] == 1000
    assert captured[3][1]["on"] is True
    assert captured[4][1]["on"] is False


def test_no_sink_falls_back_to_stdout(capsys):
    ui.print_info("plain")
    assert "plain" in capsys.readouterr().out


def test_load_config_merges_user_keys(tmp_path, monkeypatch):
    from lion_code import tui

    cfg_file = tmp_path / "tui.json"
    cfg_file.write_text(json.dumps({"theme": "nord", "keys": {"abort": "ctrl+x"}}))
    monkeypatch.setattr(tui, "CONFIG_PATH", cfg_file)
    cfg = tui.load_config()
    assert cfg["theme"] == "nord"
    assert cfg["keys"]["abort"] == "ctrl+x"          # 用户覆盖
    assert cfg["keys"]["quit"] == "ctrl+q"           # 默认保留


def test_load_config_missing_file(tmp_path, monkeypatch):
    from lion_code import tui

    monkeypatch.setattr(tui, "CONFIG_PATH", tmp_path / "nope.json")
    assert tui.load_config() == tui.DEFAULT_CONFIG


# ─── App 冒烟（fake agent，不触网）────────────────────────────


class FakeAgent:
    model = "fake-model"
    permission_mode = "default"
    use_openai = False

    def __init__(self):
        self.confirm_fn = None
        self.plan_fn = None
        self.closed = False
        self.clear_count = 0
        self.api_configured = True
        self.configured_with: dict | None = None

    def get_api_config(self):
        return {"use_openai": self.use_openai, "model": self.model, "api_key": "", "base_url": ""}

    def configure_api(self, **kwargs):
        self.configured_with = kwargs
        self.api_configured = True

    def set_confirm_fn(self, fn):
        self.confirm_fn = fn

    def set_plan_approval_fn(self, fn):
        self.plan_fn = fn

    def get_token_usage(self):
        return {"input": 1, "output": 2}

    async def chat(self, text: str) -> None:
        ui.print_assistant_text(f"echo: {text}")
        ui.print_divider()

    async def close(self):
        self.closed = True

    def clear_history(self):
        self.clear_count += 1

    def abort(self):
        pass


@pytest.mark.asyncio
async def test_app_streams_agent_output():
    tui = pytest.importorskip("lion_code.tui")
    app = tui.LionTUI(FakeAgent())
    async with app.run_test() as pilot:
        assert app.agent.confirm_fn is not None
        assert app.agent.plan_fn is not None
        app.query_one("#chat").mount  # 布局存在
        session_items = app.query_one("#sessions").query("ListItem")
        assert session_items.first().name == "__new__"

        inp = app.query_one("Input")
        inp.value = "hi"
        await inp.action_submit()
        await pilot.pause()
        assert any("echo: hi" in str(s.render()) for s in app.query(".assistant"))
    assert app.agent.closed


@pytest.mark.asyncio
async def test_app_blocks_commands_while_agent_is_working():
    tui = pytest.importorskip("lion_code.tui")
    agent = FakeAgent()
    app = tui.LionTUI(agent)
    async with app.run_test() as pilot:
        app._processing = True
        inp = app.query_one("Input")
        inp.value = "/clear"
        await inp.action_submit()
        await pilot.pause()

        assert agent.clear_count == 0
        assert any("agent is working" in str(s.render()) for s in app.query(".dim"))


@pytest.mark.asyncio
async def test_confirm_screen_roundtrip():
    tui = pytest.importorskip("lion_code.tui")
    app = tui.LionTUI(FakeAgent())
    async with app.run_test() as pilot:
        async def ask():
            return await app.agent.confirm_fn("Allow dangerous thing?")

        worker = app.run_worker(ask(), group="t")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
        assert (await worker.wait()) is True


@pytest.mark.asyncio
async def test_auto_opens_model_screen_when_unconfigured():
    tui = pytest.importorskip("lion_code.tui")
    agent = FakeAgent()
    agent.api_configured = False
    app = tui.LionTUI(agent)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, tui.ModelScreen)


@pytest.mark.asyncio
async def test_model_screen_save_configures_and_persists(tmp_path, monkeypatch):
    tui = pytest.importorskip("lion_code.tui")
    saved: list[dict] = []
    monkeypatch.setattr(tui, "save_api_config", lambda **kw: saved.append(kw))
    app = tui.LionTUI(FakeAgent())
    async with app.run_test() as pilot:
        app.action_model()
        await pilot.pause()
        assert isinstance(app.screen, tui.ModelScreen)
        app.screen.query_one("#model", Input).value = "test-model"
        app.screen.query_one("#key", Input).value = "sk-test"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert app.agent.configured_with["model"] == "test-model"
        assert app.agent.configured_with["use_openai"] is False
        assert saved == [{
            "provider": "anthropic", "model": "test-model",
            "api_key": "sk-test", "base_url": "",
        }]


# ─── Agent 无凭证构建与运行时配置 ────────────────────────────


@pytest.fixture
def no_api_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)


def test_agent_constructs_without_credentials(no_api_env):
    from lion_code.agent import Agent

    agent = Agent(api_key=None)
    assert not agent.api_configured


@pytest.mark.asyncio
async def test_chat_without_credentials_emits_error(no_api_env, captured):
    from lion_code.agent import Agent

    agent = Agent(api_key=None)
    agent._mcp_initialized = True  # 跳过真实 MCP 发现
    await agent.chat("hi")
    assert any(k == "error" and "API 未配置" in p["message"] for k, p in captured)


def test_configure_api_runtime_switch(no_api_env):
    from lion_code.agent import Agent

    agent = Agent(api_key=None)
    agent.configure_api(model="claude-x", api_key="sk-ant", use_openai=False)
    assert agent.api_configured
    assert agent.model == "claude-x"
    assert agent.get_api_config()["api_key"] == "sk-ant"

    agent.configure_api(
        model="gpt-x", api_key="sk-oai", api_base="https://x.test/v1", use_openai=True,
    )
    assert agent.use_openai
    assert agent.model == "gpt-x"
    assert agent._openai_messages[0]["role"] == "system"


def test_api_config_roundtrip(tmp_path, monkeypatch):
    from lion_code import config

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save_api_config(provider="openai", model="m", api_key="k", base_url="u")
    assert config.load_api_config() == {
        "provider": "openai", "model": "m", "api_key": "k", "base_url": "u",
    }
    (tmp_path / "config.json").write_text("{bad json")
    assert config.load_api_config() == {}
