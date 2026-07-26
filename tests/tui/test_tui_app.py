"""新 TUI 主应用(LionTuiApp)集成测试。

复用 tests/application 的 FakeProvider+Agent 装配,驱动真实
LionCodingSession,用 Textual pilot 验证:文本/工具事件渲染进
transcript、命令分发、会话侧边栏加载。

用 pytest-asyncio 而非 IsolatedAsyncioTestCase:后者强制 asyncio debug
模式,Textual 在 debug 模式下每个测试慢 10 倍以上。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import ListView

from application.test_coding_session import (
    _echo_lion_tool,
    _stop_event,
    _tooluse_event,
)
from lion_code.agent import Agent
from lion_code.application.session import LionCodingSession
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tui.app import LionTuiApp
from lion_code.tui.prompt_input import PromptInput
from lion_code.ui import set_sink


@pytest.fixture()
def app_factory():
    """构造 LionTuiApp 的工厂;负责 sink/环境变量/临时会话目录的隔离。"""
    from core.fakes import FakeProvider

    prev_sink = set_sink(lambda *_: None)
    temp_dir = tempfile.TemporaryDirectory()
    repository = SessionRepository(Path(temp_dir.name))

    def factory(events: list, registry: ToolRegistry | None = None) -> LionTuiApp:
        fake = FakeProvider(events)
        os.environ["LION_CORE_RUNTIME"] = "1"
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry or ToolRegistry(),
                custom_system_prompt="test",
                session_repository=repository,
            )
        agent._mcp_initialized = True
        return LionTuiApp(LionCodingSession(agent))

    yield factory
    set_sink(prev_sink)
    os.environ.pop("LION_CORE_RUNTIME", None)
    temp_dir.cleanup()


async def _submit(app: LionTuiApp, pilot, text: str) -> None:
    prompt = app.query_one("#prompt", PromptInput)
    prompt.text = text
    prompt.focus()
    await pilot.press("enter")


@pytest.mark.asyncio
async def test_text_message_renders_into_transcript(app_factory) -> None:
    app = app_factory([_stop_event("你好,Lion")])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "hi")
        await app.workers.wait_for_complete()
        await pilot.pause()

    roles = [(item.role, item.text) for item in app.state.items]
    assert ("user", "hi") in roles
    assert any(r == "assistant" and "你好" in t for r, t in roles)
    assert not app.session.is_running


@pytest.mark.asyncio
async def test_tool_loop_renders_tool_item(app_factory) -> None:
    registry = ToolRegistry()
    registry.register(_echo_lion_tool())
    app = app_factory([_tooluse_event(), _stop_event("done")], registry)
    async with app.run_test() as pilot:
        await _submit(app, pilot, "hi")
        await app.workers.wait_for_complete()
        await pilot.pause()

    tool_items = [item for item in app.state.items if item.role == "tool"]
    assert len(tool_items) == 1
    assert tool_items[0].tool_name == "echo"
    assert "echo:hi" in (tool_items[0].tool_result_text or "")


@pytest.mark.asyncio
async def test_cost_and_unknown_commands(app_factory) -> None:
    app = app_factory([])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "/cost")
        await pilot.pause()
        await _submit(app, pilot, "/nonsense")
        await pilot.pause()

    status_texts = [item.text for item in app.state.items if item.role == "status"]
    assert any(t.startswith("tokens:") for t in status_texts)
    assert any("未知命令" in t for t in status_texts)


@pytest.mark.asyncio
async def test_clear_command_resets_transcript(app_factory) -> None:
    app = app_factory([_stop_event("first")])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "hi")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.state.items
        await _submit(app, pilot, "/clear")
        await app.workers.wait_for_complete()
        await pilot.pause()

    # /clear 后 Agent 会经 sink 发一条 "Conversation cleared." 状态行;
    # 对话内容(user/assistant/tool)必须清空。
    conversation = [
        item for item in app.state.items if item.role in ("user", "assistant", "tool")
    ]
    assert conversation == []
    assert app.session.messages == ()


@pytest.mark.asyncio
async def test_slash_opens_command_completions(app_factory) -> None:
    from textual.widgets import Static

    app = app_factory([])
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", PromptInput)
        prompt.focus()
        await pilot.press("slash")
        await pilot.pause()

        displays = [item.display for item in app._completion_state.items]
        assert "/model" in displays
        assert "/theme" in displays
        assert app.query_one("#autocomplete", Static).display

        # Tab 接受选中项写回输入框,Esc 关闭补全。
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text.startswith("/") and len(prompt.text) > 1
        await pilot.press("escape")
        await pilot.pause()
        assert not app._completion_state.items


@pytest.mark.asyncio
async def test_completion_navigation_moves_selection(app_factory) -> None:
    app = app_factory([])
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", PromptInput)
        prompt.focus()
        await pilot.press("slash")
        await pilot.pause()
        first = app._completion_state.selected_index
        await pilot.press("down")
        await pilot.pause()
        assert app._completion_state.selected_index == first + 1
        await pilot.press("up")
        await pilot.pause()
        assert app._completion_state.selected_index == first


@pytest.mark.asyncio
async def test_model_picker_lists_and_applies_choice(app_factory, tmp_path, monkeypatch) -> None:
    from lion_code import config as config_module
    from lion_code.application.provider_settings import remember_model
    from lion_code.tui.app import ModelPickerScreen

    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")
    remember_model(provider="openai", model="model-alpha")

    app = app_factory([])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "/model")
        await pilot.pause()
        assert isinstance(app.screen, ModelPickerScreen)
        labels = [c.model for c in app.screen.visible_choices]
        assert "model-alpha" in labels

        # 搜索过滤 + Enter 选中即切换模型并持久化。
        search = app.screen.query_one("#model-picker-search")
        search.value = "alpha"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.session.model == "model-alpha"
    saved = config_module.load_api_config()
    assert saved["known_models"][0]["model"] == "model-alpha"


@pytest.mark.asyncio
async def test_model_picker_accepts_custom_typed_name(app_factory, tmp_path, monkeypatch) -> None:
    from lion_code import config as config_module
    from lion_code.tui.app import ModelPickerScreen

    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")

    app = app_factory([])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "/model")
        await pilot.pause()
        assert isinstance(app.screen, ModelPickerScreen)
        search = app.screen.query_one("#model-picker-search")
        search.value = "my-brand-new-model"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.session.model == "my-brand-new-model"


@pytest.mark.asyncio
async def test_model_command_with_arg_sets_directly(app_factory, tmp_path, monkeypatch) -> None:
    from lion_code import config as config_module

    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")

    app = app_factory([])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "/model direct-model")
        await pilot.pause()

    assert app.session.model == "direct-model"


@pytest.mark.asyncio
async def test_resume_picker_restores_previous_session(app_factory) -> None:
    from lion_code.tui.app import SessionPickerScreen

    app = app_factory([_stop_event("first")])
    async with app.run_test() as pilot:
        await _submit(app, pilot, "hi")
        await app.workers.wait_for_complete()
        await pilot.pause()
        old_id = app.session.session_id
        assert app.session.messages

        await _submit(app, pilot, "/clear")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.session.messages == ()
        assert app.session.session_id != old_id

        await _submit(app, pilot, "/resume")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, SessionPickerScreen)
        ids = [meta.get("id") for meta in app.screen.visible_sessions]
        assert old_id in ids

        # 用 id 过滤,消除对真实 home 会话目录里其它会话的顺序依赖。
        search = app.screen.query_one("#session-picker-search")
        search.value = old_id
        await pilot.pause()
        assert [m.get("id") for m in app.screen.visible_sessions] == [old_id]
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert app.session.session_id == old_id
    assert [m.role for m in app.session.messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_sessions_sidebar_lists_new_entry(app_factory) -> None:
    app = app_factory([])
    async with app.run_test() as pilot:
        await pilot.pause()
        lv = app.query_one("#sessions", ListView)
        names = [item.name for item in lv.children]
    assert "__new__" in names
