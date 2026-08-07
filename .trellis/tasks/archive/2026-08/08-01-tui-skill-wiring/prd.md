# TUI /skill: 接线到权威 skill 路径

## Goal

把 TUI /skill:name args 接到 lion_code.skills.resolve_skill_prompt(与 REPL /<name> 一致)再 agent.chat,并恢复 /skill: 自动补全与 state.py 展示分支。前置:二阶段已先删除 /skill: 入口与 tau <skill> 块机器(见 m-012)。本任务为预留,待删除稳定后实施。

## Requirements

- R1：`CommandRegistry.execute` 在未命中内置命令时按 `/<skill-name> [args]` fallback 到 `lion_code.skills.get_skill_by_name`；与 REPL `__main__.py` 逻辑一致。
- R2：`inline` Skill 直接把 `resolve_skill_prompt` 结果作为 `agent.chat` 输入；`fork` Skill 改用 skill 工具调用入口。
- R3：`/skills` 命令列出可用 Skill，TUI 和 REPL 行为一致。
- R4：TUI 自动补全在输入 `/` 时展示用户可调用 Skill 名称作为候选项。
- R5：TUI `_dispatch` 处理 `skill_prompt` 意图，用 `agent.chat` 执行解析后的提示词。
- R6：不修改 Skill 发现、解析、执行或存储逻辑；不新增 Skill 类型或上下文模式。

## Acceptance Criteria

- [x] `/<skill-name> [args]` 在 TUI 中正确解析并执行（inline 和 fork 两种上下文）。
- [x] `/skills` 命令在 TUI 中列出可用 Skill。
- [x] TUI 自动补全在输入 `/` 时展示用户可调用 Skill 名称。
- [x] REPL `__main__.py` 的既有 skill 路径不受影响。
- [x] 全量测试、compileall、import-linter 通过；无新增 ruff/mypy/format 基线回归。
  （584 passed / 6 skipped；5 contracts KEPT；compileall OK）

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
