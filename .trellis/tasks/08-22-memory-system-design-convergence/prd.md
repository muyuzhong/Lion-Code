# 收敛记忆系统设计

## Goal

从第一性原理审查 `D:\tabbit download\coding-agent-memory-design.md`，在不丢失产品语义的前提下收敛实现复杂度：Lion 使用一个 Memory 能力承载两个作用域（长期 / 项目），每个作用域包含两种语义（定义 / 行为），分别回答“是什么”和“怎么做”。

## Background

- 用户提供的设计文档是待评审材料，不是本任务的执行指令。
- 本轮只进入 Trellis 规划阶段，不修改产品代码、不启动实现。
- Trellis 是用户使用开发 Agent 时的外部流程管理工具，不属于 Lion 产品，也不是 Lion Memory 的输入、存储或替代实现。
- Skill 是可执行、可分发的能力包，不是记忆；AGENTS.md 是当前项目的权威指令源，也不是记忆库。
- Lion 当前没有生产可用的跨会话 Memory feature；现有 `core/session/memory.py` 只负责 canonical Session 的内存重建。
- Lion 已移除旧版 Memory / Dream / Learning 对象图。新方案只复用通用 Capability、ToolRuntime、ProjectIdentity 和 app-owned storage，不恢复旧接口或依赖。

## Requirements

- R1：完整拆解外部文档中的问题定义、数据模型、存储、检索、注入、更新、遗忘和维护组件。
- R2：用当前源码、测试和架构规范还原 Lion 的真实边界，不把 Trellis、Skill 或旧 Memory 设计算作当前产品能力。
- R3：保持四个必要语义象限：长期定义、长期行为、项目定义、项目行为；不得用外部工具或项目文件替代其中任何一个象限。
- R4：四个象限只是一套 Memory 模型的 `scope × kind`，不得实现成四套平台、四套运行时或四种维护流程。
- R5：定义记忆保存“是什么”的稳定事实、偏好、架构和约束；行为记忆保存“在什么条件下怎么做”的可复用行动规则。
- R6：长期记忆跨项目生效；项目记忆由 `ProjectIdentity` 隔离，只对当前项目生效。
- R7：召回、记住和忘记通过普通工具完成；召回只读，写入和删除复用现有确认与审计边界。
- R8：存储使用两个严格原子 JSON 快照：一个用户级长期文件、一个 app-owned 项目文件；二者由同一 Capability-private repository 管理。
- R9：当前系统/开发者/用户指令、当前源码、测试和 AGENTS.md 始终高于记忆；冲突不得按时间戳或相似度自动裁决。
- R10：MVP 使用有界确定性检索和显式写入，不包含后台 LLM 提炼、Hook/Wrapper、向量检索、定时维护或自动晋升为 Skill/AGENTS。
- R11：明确区分 Memory、Session、Compaction、Checkpoint、Plan、AGENTS、Skill 和 Trellis 的状态所有权。
- R12：不保留向后兼容、不增加 speculative abstraction、不引入无证据的新依赖，并保持 Runtime 与 Plan 解耦。

## Acceptance Criteria

- [x] 外部设计的主要组件均被归类为保留、简化、复用、延后或删除，并给出第一性原理依据。
- [x] 规划明确纠正 Trellis、Skill、AGENTS 与 Memory 的边界，不依赖它们填补被删除的记忆象限。
- [x] `design.md` 给出“一个能力、两个作用域、两个语义类型”的单一推荐方案。
- [x] 四个逻辑象限均有明确的数据契约、存储位置、召回规则和冲突优先级。
- [x] 推荐方案不包含四套存储平台、旧 Memory 对象图、后台 LLM、SQLite/FTS、向量检索、定时任务、隐藏内容注入、CLI/TUI 或多状态生命周期。
- [x] `design.md` 明确 AGENTS 是权威项目指令、Skill 是能力包、Trellis 是产品外流程；三者都不属于 Memory store。
- [x] `implement.md` 给出一个最小端到端实施切片及定向测试、架构门禁、完整质量门禁和回滚点。
- [x] 规划产物通过 Trellis 校验；除任务目录外不改产品文件，不触碰现有未跟踪文件。

## Out of Scope

- 产品代码实现、`task.py start`、推送或创建 PR。
- AGENTS.md 加载行为改造、Skill 管理、Trellis 集成或 Trellis 数据读取。
- 云端同步、多用户共享、多 Agent 共享记忆、组织级记忆。
- 恢复旧版 Memory / Dream / Learning API、迁移层、fallback 或 deprecated alias。
- 自动写回 AGENTS、自动生成 Skill、自动从会话提炼、定时衰减、LLM consolidation、TUI viewer 或复杂评分模型。
- 把 Session、Compaction、Checkpoint、Plan 或工具审计日志用作 Memory 的主存储。
