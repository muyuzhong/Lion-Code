# 三阶段-4：提取 Learning Runtime

## Goal

把显式 `/learn` 的会话经验沉淀流程从 `Agent` 提取到 `LearningRuntime`，让
`Agent` 保留稳定的 `learn_from_current_session()` 入口和运行时组装职责。

## Confirmed Facts

- 当前实现只包含一次性 `/learn` 流程，而没有学习队列、知识图谱或后台学习循环：
  `Agent.learn_from_current_session()`（`lion_code/agent.py:1465`）序列化
  Core 消息、调用 evaluator、提取 JSON 决策，并在接受时调用 `create_skill()`。
- CLI 的 `/learn` 仅等待并展示 `Agent.learn_from_current_session()` 的返回值
  （`lion_code/__main__.py:179-181`），因此该协程的返回文本和异常语义是兼容边界。
- 既有特征测试位于 `tests/test_learning.py`，已覆盖创建与拒绝决策；无效 JSON 和
  缺少创建字段仍由现有实现统一抛出 `ValueError("Invalid Meta-Skill response")`。
- 该切片约 40 行，适合保持 PRD-only 的轻量任务，不引入新的持久化、异步任务或
  产品行为。

## Requirements

- R1：新增 `lion_code/learning_runtime.py`，由它拥有 Meta-Skill 提示词、会话转录、
  evaluator 调用、JSON 决策解析以及 Skill 创建。
- R2：`Agent` 在初始化时组装该运行时，并以薄委托保留
  `async learn_from_current_session() -> str`；正常返回值和错误文本/异常须与迁移前一致。
- R3：运行时只能经窄 Host 协议访问 Core 消息和 evaluator side-query，不能反向导入
  `Agent` 或承担 Provider、CLI、会话持久化职责。
- R4：保留 `lion_code.agent.LEARN_META_SKILL_PROMPT` 的导入兼容性，避免破坏已有
  测试或外部直接导入者。
- R5：测试应同时锁定 Agent 委托路径与运行时的创建、拒绝和无效响应行为；不修改
  `/learn` 命令格式或 `create_skill()` 的覆盖策略。

## Acceptance Criteria

- [ ] AC1：`LearningRuntime` 独立拥有 `/learn` 决策流程，`agent.py` 只保留组装和薄委托。
- [ ] AC2：`/learn` 仍使用一次 evaluator 调用、`max_tokens=4096`、当前工作目录与
  Core JSON 转录；接受和拒绝时的可观察返回文本保持不变。
- [ ] AC3：无 JSON、无闭合 JSON 或接受决策缺少 `name`、`content`、`scope` 时，仍抛出
  `ValueError("Invalid Meta-Skill response")`，且不写入 Skill。
- [ ] AC4：`LEARN_META_SKILL_PROMPT` 可继续从 `lion_code.agent` 导入；新模块不在模块级
  导入 `Agent`。
- [ ] AC5：`tests/test_learning.py` 及相关回归测试、`compileall`、导入边界和差异检查通过；
  已知全仓静态质量基线只记录差异，不在本切片顺带清理。

## Out of Scope

- 学习队列、知识图谱、后台任务、自动学习触发器或新的 `/learn` UX。
- 修改 Meta-Skill 的产品提示词、技能格式、项目/用户 scope 规则或覆盖策略。
- Core Runtime、会话 Memory、Autonomy、子 Agent 或历史 Ruff/format/mypy 基线清理。

## Technical Decision

采用与既有 `AutonomyRuntime`、`SessionMemoryCoordinator` 一致的窄 Host 协议：
`LearningRuntime` 接收 Host，只回调 `_core_runtime.messages` 和
`_run_evaluator_query()`；`create_skill()` 与 `Path.cwd()` 属于该运行时自身的确定性职责。
为保障现有导入，`agent.py` 从新模块重导入提示词常量并持有运行时实例。

## Validation Plan

- 运行 `python -m pytest -q tests/test_learning.py`，并补充/运行相邻 Agent 回归测试。
- 运行 `python -m compileall -q lion_code tests`、针对新增模块的 Ruff 与 mypy、
  `lint-imports --no-cache`、`git diff --check` 及 Trellis task validation。
- 最后运行完整 `python -m pytest -q`，并如实记录与当前基线的差异。

## Planning Status

阻塞问题为空。该计划只提取现有 `/learn` 流程，未扩展产品能力；等待用户对本摘要的
明确实现批准后才启动任务并修改运行时代码。
