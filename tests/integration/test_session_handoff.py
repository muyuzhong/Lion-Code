"""PR2 显式 Session handoff：九段摘要带入新 Session 的验收测试。

覆盖 PRD 验收标准：
- 九段摘要完整、source branch root 正确；
- 旧 Session append-only 历史不变、仍可 restore；
- 新 Session 首段为 BranchSummaryEntry 且有界（不复制旧 raw messages）；
- 连续 handoff chain 可追溯；
- 失败原子性（compaction 失败 / 写入失败回滚，无半初始化新 Session）；
- 普通 new_session 保持干净会话语义。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.fakes import FakeProvider

from lion_code.context import SUMMARY_HEADINGS, CompactionRequest, ContextCompactor
from lion_code.core.messages import AssistantMessage, TextContent
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.core.session import BranchSummaryEntry
from lion_code.meta_agent import build_meta_agent
from lion_code.session_runtime import SessionRecorder, SessionRepository

_VALID_SUMMARY = "\n\n".join(
    f"{heading}\ncarried task state" for heading in SUMMARY_HEADINGS
)


def _done(text: str) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
        ),
    )


class _NineHeadingCompactor(ContextCompactor):
    """记录 request 并返回合法九段摘要，验证 handoff 复用既有压缩契约。"""

    def __init__(self) -> None:
        self.requests: list[CompactionRequest] = []

    async def summarize(self, request: CompactionRequest) -> str:
        self.requests.append(request)
        return _VALID_SUMMARY


class _FailingCompactor(ContextCompactor):
    async def summarize(self, _request: CompactionRequest) -> str:
        raise RuntimeError("compaction provider exploded")


def _build_agent(tmp_path: Path, compactor: ContextCompactor, events: list) -> object:
    return build_meta_agent(
        provider=FakeProvider(events),
        tools=[],
        session_repository=SessionRepository(tmp_path / "sessions"),
        context_compactor=compactor,
    )


async def _run_turn(agent, prompt: str, text: str) -> None:
    provider = agent.provider
    provider._events.append(_done(text))
    result = await agent.run(prompt)
    assert result.final_text == text


def _branch_summary_entry(state) -> BranchSummaryEntry:
    entries = [e for e in state.entries if isinstance(e, BranchSummaryEntry)]
    assert len(entries) == 1
    return entries[0]


async def test_handoff_carries_nine_heading_summary_with_old_session_root(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    compactor = _NineHeadingCompactor()
    agent = _build_agent(tmp_path, compactor, [])
    await _run_turn(agent, "fix the login bug", "working on it")
    await _run_turn(agent, "continue with tests", "tests added")

    old_session_id = agent.session_id
    repository = SessionRepository(tmp_path / "sessions")
    old_state_before = await repository.load(old_session_id)
    old_entry_ids = [entry.id for entry in old_state_before.entries]
    old_messages_before = [message.text for message in agent.messages]

    await agent.handoff_session()

    new_session_id = agent.session_id
    assert new_session_id != old_session_id

    # 新 Session：首段为 BranchSummaryEntry，九段完整、root 指向旧 Session。
    new_state = await repository.load(new_session_id)
    branch = _branch_summary_entry(new_state)
    assert branch.branch_root_id == old_session_id
    for heading in SUMMARY_HEADINGS:
        assert heading in branch.summary
    assert new_state.entries.index(branch) == 3  # session_info/model/thinking 之后

    # 有界：新 Session 只承载摘要，不复制旧 raw messages。
    assert len(new_state.messages) == 1
    assert "summary of a branch" in new_state.messages[0].text
    assert "carried task state" in new_state.messages[0].text
    assert len(agent.messages) == 1
    assert agent.messages[0].text == new_state.messages[0].text

    # 旧 Session append-only 历史不变，仍可 restore。
    old_state_after = await repository.load(old_session_id)
    assert [entry.id for entry in old_state_after.entries] == old_entry_ids
    assert await agent.restore(old_session_id) is True
    assert [message.text for message in agent.messages] == old_messages_before
    await agent.close()


async def test_handoff_reuses_compaction_contract_without_second_prompt(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    compactor = _NineHeadingCompactor()
    agent = _build_agent(tmp_path, compactor, [])
    await _run_turn(agent, "fix the login bug", "working")

    await agent.handoff_session()

    assert len(compactor.requests) == 1
    request = compactor.requests[0]
    # 全量旧历史进入压缩投影（handoff 不保留 recent suffix）。
    assert "fix the login bug" in request.history_projection
    assert "working" in request.history_projection
    # 目标解析复用 compaction 契约：最近一条用户消息成为当前任务。
    assert request.objective is not None
    assert request.objective.startswith("Current task:")
    assert "fix the login bug" in request.objective
    await agent.close()


async def test_handoff_chain_is_traceable(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])

    await _run_turn(agent, "root task", "root done")
    session_a = agent.session_id

    await agent.handoff_session()
    session_b = agent.session_id
    await _run_turn(agent, "second stage", "stage done")

    await agent.handoff_session()
    session_c = agent.session_id

    repository = SessionRepository(tmp_path / "sessions")
    branch_b = _branch_summary_entry(await repository.load(session_b))
    branch_c = _branch_summary_entry(await repository.load(session_c))
    assert branch_b.branch_root_id == session_a
    assert branch_c.branch_root_id == session_b

    # 链上任意节点仍可独立 restore。
    assert await agent.restore(session_a) is True
    assert [m.text for m in agent.messages] == ["root task", "root done"]
    await agent.close()


async def test_handoff_compaction_failure_is_atomic(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _FailingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id
    messages_before = list(agent.messages)
    repository = SessionRepository(tmp_path / "sessions")
    sessions_before = await repository.list_sessions()

    with pytest.raises(RuntimeError, match="compaction provider exploded"):
        await agent.handoff_session()

    # 旧 Session 完好，且没有留下任何半初始化新 Session。
    assert agent.session_id == old_session_id
    assert list(agent.messages) == messages_before
    assert await repository.list_sessions() == sessions_before
    await agent.close()


async def test_handoff_write_failure_rolls_back_to_old_session(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id
    messages_before = list(agent.messages)
    repository = SessionRepository(tmp_path / "sessions")

    async def _failing_branch_summary(self, *, summary, branch_root_id=None):
        raise OSError("disk full")

    monkeypatch.setattr(
        SessionRecorder, "record_branch_summary", _failing_branch_summary
    )

    with pytest.raises(OSError, match="disk full"):
        await agent.handoff_session()

    # 回滚：身份、活跃上下文回到旧 Session；半初始化新 JSONL 被清理。
    assert agent.session_id == old_session_id
    assert list(agent.messages) == messages_before
    listings = await repository.list_sessions()
    assert [item["id"] for item in listings] == [old_session_id]
    assert listings[0]["messageCount"] == 2
    assert await agent.restore(old_session_id) is True
    await agent.close()


async def test_handoff_without_messages_fails_cleanly(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    session_id = agent.session_id

    with pytest.raises(RuntimeError, match="messages to carry over"):
        await agent.handoff_session()

    assert agent.session_id == session_id
    assert agent.messages == ()
    await agent.close()


async def test_new_session_stays_clean_after_handoff_exists(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")

    await agent.new_session()

    repository = SessionRepository(tmp_path / "sessions")
    clean_state = await repository.load(agent.session_id)
    assert not [
        entry for entry in clean_state.entries if isinstance(entry, BranchSummaryEntry)
    ]
    assert agent.messages == ()
    assert clean_state.messages == ()
    await agent.close()


async def test_handoff_requires_recorder_and_compactor(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")

    # 复位前置失败：不动任何会话状态。
    agent._agent_runtime._context._context_compactor = None
    with pytest.raises(RuntimeError, match="requires a recorder and a compactor"):
        await agent.handoff_session()
    await agent.close()


async def test_handoff_rejects_context_mismatch(tmp_path, monkeypatch) -> None:
    from lion_code.runtime.session import SessionRuntime

    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id

    async def _short_ids(_self) -> tuple[str, ...]:
        return ()

    monkeypatch.setattr(SessionRuntime, "context_entry_ids", _short_ids)
    with pytest.raises(RuntimeError, match="does not match"):
        await agent.handoff_session()
    assert agent.session_id == old_session_id
    await agent.close()


async def test_handoff_rejects_unloadable_current_session(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id

    async def _missing(_self, _session_id):
        return None

    monkeypatch.setattr(SessionRepository, "load", _missing)
    with pytest.raises(RuntimeError, match="could not be loaded"):
        await agent.handoff_session()
    assert agent.session_id == old_session_id
    await agent.close()


async def test_handoff_rolls_back_when_new_session_disappears(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id
    messages_before = list(agent.messages)
    repository = SessionRepository(tmp_path / "sessions")
    real_load = SessionRepository.load
    load_calls = 0

    async def _flaky_load(self, session_id):
        # 第一次（读旧 Session）成功；第二次（读新 Session）返回 None。
        nonlocal load_calls
        load_calls += 1
        if load_calls >= 2:
            return None
        return await real_load(self, session_id)

    monkeypatch.setattr(SessionRepository, "load", _flaky_load)
    with pytest.raises(RuntimeError, match="Session disappeared after handoff"):
        await agent.handoff_session()

    assert agent.session_id == old_session_id
    assert list(agent.messages) == messages_before
    # load 已被 patch，直接看磁盘：只剩旧 Session，无半初始化新 JSONL。
    assert sorted(path.stem for path in repository.session_dir.glob("*.jsonl")) == [
        old_session_id
    ]
    await agent.close()


async def test_handoff_rolls_back_when_new_session_switch_fails_internally(
    tmp_path, monkeypatch
) -> None:
    from lion_code.capabilities.runtime import CapabilityRuntime

    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id
    messages_before = list(agent.messages)
    repository = SessionRepository(tmp_path / "sessions")

    async def _failing_on_new_session(_self) -> None:
        # 模拟 new_session 在身份已切换后失败，覆盖回滚窗口。
        raise RuntimeError("capability reset failed")

    monkeypatch.setattr(CapabilityRuntime, "on_new_session", _failing_on_new_session)
    with pytest.raises(RuntimeError, match="capability reset failed"):
        await agent.handoff_session()

    assert agent.session_id == old_session_id
    assert list(agent.messages) == messages_before
    listings = await repository.list_sessions()
    assert [item["id"] for item in listings] == [old_session_id]
    await agent.close()


async def test_handoff_rollback_failure_still_deletes_half_initialized_session(
    tmp_path, monkeypatch
) -> None:
    from lion_code.runtime.agent import AgentRuntime

    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    await _run_turn(agent, "fix the login bug", "working")
    old_session_id = agent.session_id
    repository = SessionRepository(tmp_path / "sessions")
    real_load = SessionRepository.load
    load_calls = 0

    async def _flaky_load(self, session_id):
        # 第一次（读旧 Session）成功；第二次（读新 Session）触发 handoff 失败。
        nonlocal load_calls
        load_calls += 1
        if load_calls >= 2:
            return None
        return await real_load(self, session_id)

    async def _failing_activate(_self, _state) -> None:
        # 回滚激活自身失败：清理仍必须执行，否则半初始化新 JSONL 残留磁盘。
        raise RuntimeError("activation exploded")

    monkeypatch.setattr(SessionRepository, "load", _flaky_load)
    monkeypatch.setattr(AgentRuntime, "_activate_session", _failing_activate)
    with pytest.raises(RuntimeError, match="activation exploded"):
        await agent.handoff_session()

    assert sorted(path.stem for path in repository.session_dir.glob("*.jsonl")) == [
        old_session_id
    ]
    await agent.close()


async def test_session_runtime_record_branch_summary_requires_recorder(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    agent = _build_agent(tmp_path, _NineHeadingCompactor(), [])
    session_runtime = agent._agent_runtime._session
    recorder = session_runtime.recorder
    session_runtime._recorder = None
    try:
        with pytest.raises(RuntimeError, match="No session recorder"):
            await session_runtime.record_branch_summary(
                summary="x",
                branch_root_id="old",
            )
    finally:
        session_runtime._recorder = recorder
    await agent.close()
