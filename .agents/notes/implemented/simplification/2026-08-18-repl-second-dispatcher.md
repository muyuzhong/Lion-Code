# Agent Note: 删除 REPL 的第二套斜杠命令分发（回到单一 dispatcher）

- Status: implemented
- 日期: 2026-08-18
- 范围: `lion_code/__main__.py`、`lion_code/application/`、`tests/tui/`、`tests/application/`

## Problem

`__main__.py` 的 REPL 先调用 `command_session.handle_command(inp)`（:142，
`application/session.py` 经 `application/commands.py` 的 SlashCommand 注册表分发），
**丢弃**返回的 `CommandResult`，随后在 :144-189 用裸 `if/elif` 重新实现
`/clear` `/plan` `/cost` `/compact` `/skills` 以及 skill 回退——同一批命令两套
实现。这直接违反 `runtime-boundaries.md:80-81` 的明文契约：
"The REPL may render terminal output but must not own a second command dispatcher"。
两套实现对同一命令的行为可能漂移（例如 `/skills` 的展示逻辑只在 REPL 副本里，
`/compact` 的错误处理也不同），且新增命令时必须记得同时在两处接线。

## Proposal

1. 删除 `__main__.py:144-189` 的 REPL 内联分支，改为消费
   `command_session.handle_command()` 返回的 `CommandResult`（TUI 已经在用同一
   协议：`tui/app.py:1187-1217` 按 `result.*` 标志分发）。
2. REPL 特有的能力（如 skill 内联/`fork` 触发）若 application 层没有对应命令，
   在 `application/commands.py` 增加对应 SlashCommand（或确认 `/skills` 与
   skill 回退在 application 层已有等价路径后直接复用）。
3. 删除 README 中任何描述 REPL 拥有命令分发的措辞（如有）。

## Why not keep it

辩护是「REPL 不依赖 application 层、保持轻量」——但 application 层命令表面就是
为 REPL/TUI 共享而设的（`runtime-boundaries.md` 明令 REPL 不得自建第二分发器），
TUI 已经证明 `CommandResult` 协议够用。两套分发的维护成本（同命令不同行为）大于
一次性接线成本；`AGENTS.md` 原则 3（模块化、关注点分离）也指向单一 command owner。

## Acceptance criteria

- `__main__.py` 中不再出现 `/clear` `/plan` `/cost` `/compact` 的内联分支；
  REPL 与 TUI 对同一命令走同一实现。
- `rg -n "handle_command" __main__.py` 有且仅有一个入口；`CommandResult` 的
  `handled=False` 分支在 REPL 明确处理。
- REPL 命令回归（`/clear` `/plan` `/cost` `/compact` `/skills`、未知命令、
  skill 回退）通过；全量可跑 unittest 通过。

## Risks

- REPL 的 plan 审批走 `print_plan_for_approval` + `input`，依赖 application 层
  的 notice/confirm 回调链路——接线时需要保持同样的终端呈现（TUI 已示范做法）。
- `/skills` 在 REPL 中的输出样式与 application 层可能不同，迁移后样式可能略变——
  属可接受的呈现差异。
## 落地

- 提交: 6a82197（分支 simplify/repl-single-dispatcher）
- 验证: run_repl 消费 CommandResult 单一分发；新增 test_repl_unknown_command_prints_hint。门禁：全量 712 passed（同 5 个既有失败）。
