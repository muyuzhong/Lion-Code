# Agent Note: 删除 skill discovery 死代码对（create_skill/reset_skill_cache）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/capabilities/skill/discovery.py`

## Problem

`capabilities/skill/discovery.py` 的「创建 SKILL.md + 清缓存」入口没有任何消费者：

1. `create_skill(name, content, scope)`（`discovery.py:146-159`）：全仓 `rg "create_skill\("` 只命中定义本身；生产（`lion_code/`、`scripts/`、`desktop/`）、tests、docs、README 均零命中。
2. `reset_skill_cache()`（:141-143）：唯一调用点就是 `create_skill` 内部（:158）。
3. 技能运行时（`skill/runtime.py:26`）与命令层（`application/commands.py:182-200`、`application/session.py:270-280`）只消费读路径（`discover_skills`/`get_skill_by_name`/`execute_skill`/`resolve_skill_prompt`），没有任何「写技能文件」的入口。

## Proposal

删除 `create_skill`、`reset_skill_cache` 两个函数及 `_cached_skills` 的失效路径（读缓存不受影响，当前无运行时写入者）；无测试/文档引用需同步（已逐一核验）。

## Why not keep it

整条「模型提炼并落盘 SKILL.md」机制是未接线的投机面：没有任何产品命令或能力工具调用它。按「没有调用者就不存在」与项目先例（memory 的 add-then-remove 审计）删除；若未来要做「落盘技能」命令，按现有 `@include`/skill 框架加回约 20 行。

## Acceptance criteria

- `rg -n "create_skill|reset_skill_cache" lion_code/ tests/ scripts/` 零命中。
- `tests/capabilities/test_capability_migration.py`、`tests/tooling/`（skill 相关）全绿。

## Risks

- 若未来模型需要「将提炼出的技能写入项目 `.claude/skills`」，需重建该入口——当前零消费者，风险可接受。