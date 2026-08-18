# Agent Note: 删除 AgentEndEvent/SessionAgentEndEvent 的双转录 messages 负载

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/core/loop.py`、`lion_code/core/events.py`、`lion_code/application/session.py`、`lion_code/application/events.py`、`tests/application/test_coding_session_ports.py`

## Problem

`core/loop.py` 维护了一份 `new_messages` 列表（:93-95 初始化，:106/:126-127/
:136-137/:183-184/:211/:235/:259 并行追加），在 :110/:140/:188/:215/:275 五个终止
点放进 `AgentEndEvent(messages=new_messages)`。这份列表是 `messages` 的精确镜像——
同一个事实的第二次表示，专为没人读的事件负载服务：

- `application/session.py:480` 把 `event.messages` 抄进
  `SessionAgentEndEvent.messages`（`application/events.py:35`）之后，
  两处负载都没有任何读取者：TUI 与 Supervisor 按事件类型消费
  （`tui/app.py:1051-1053`、`tui/adapter.py:29-32`、`supervisor.py:908-925`），
  不读 messages；`tests/application/test_coding_session_ports.py:43` 只在构造时传参。
- `application/events.py` 的文档本身警告 AgentEnd 不是一轮的终点（steering/
  overflow-retry 还会继续），事件快照在发出的那一刻就已过期——这正是没人读它的原因。

## Proposal

1. 从 `AgentEndEvent` 与 `SessionAgentEndEvent` 删除 `messages` 字段。
2. 删除 `core/loop.py` 里整个 `new_messages` 记账：五个终止点改发
   `AgentEndEvent()`（不携带负载）。
3. 删除 `application/session.py:480` 的 `messages=event.messages` 映射与
   `tests/application/test_coding_session_ports.py:43` 的构造传参。

## Why not keep it

辩护是「迟到订阅者可以直接拿到轮次快照」——但规范转录本已经由
`session.messages`/JSONL 重放可及（`runtime-boundaries.md` 的 canonical session
路径），且事件快照因语义注定过期。`events.py` 自己的文档注释指出了这一点；
保留只是一份没人读的过期拷贝。

## Acceptance criteria

- `rg -n "new_messages|event\.messages|messages=event" lion_code` 零命中。
- 集成测试（`test_agent_core_runtime.py` 的 turn/事件断言、应用层
  `test_application_coding_session.py`）全绿；Supervisor 的
  `_observe_event` 按类型分支不受影响。
- 全量可跑 unittest 通过。

## Risks

- `AgentEndEvent` 是 Pi 兼容线事件（`core/provider_events.py` 同族）——若外部
  消费者依赖该负载字段，属于契约缩减；当前仓库唯一消费者是
  application/TUI/Supervisor（均按类型消费），风险可接受。