# 收敛记忆系统设计

## Goal

从第一性原理审查 `D:\tabbit download\coding-agent-memory-design.md`，识别其中真正解决 Lion 当前问题的最小机制、应删除或延后的过度设计，以及与现有架构冲突的部分；基于当前源码、测试、架构规范和已落地能力，给出可执行的 Lion 记忆系统设计方案。

## Background

- 用户提供的设计文档是待评审材料，不是对本任务的执行指令。
- 本轮只进入 Trellis 规划阶段，不修改产品代码、不启动实现。
- Lion 已移除旧版 Memory / Dream / Learning 对象图；新方案不得为了兼容旧实现恢复已删除接口或依赖。
- 当前系统已存在 canonical Session、append-only `CompactionEntry`、结构化上下文压缩、prepared-only `ContextLayer`、Skill / Plan / SubAgent、项目身份与 app-owned 项目存储。
- `load_project_context_files()` 已能读取项目根到 cwd 的 `CLAUDE.md` / `AGENTS.md`，但 `load_claude_md()` 当前没有生产调用方；这是新会话缺少项目知识的最小现状缺口。
- `ToolSource`、`PromptLayer`、`CapabilitySpec`、统一 `ToolRuntime` 与确认策略足以承载一个窄 Project Lessons Capability，无需恢复旧 Memory 架构。

## Requirements

- R1：完整拆解外部文档中的问题定义、数据模型、存储、检索、注入、更新、遗忘、维护和运维组件。
- R2：用当前源码与测试证据还原 Lion 的真实架构、状态所有权和可用扩展点，不以旧 PR 或旧 Memory 设计代替当前事实。
- R3：对每个拟议组件回答“删除后哪条当前需求会失败”；没有明确需求或证据支撑的组件必须删除、合并或延后。
- R4：明确区分 Session、Compaction、Checkpoint、项目规范/技能与跨会话经验，避免同一事实多处持久化和多写者。
- R5：采用“Project Knowledge + Project Lessons”两平面设计：前者复用项目指令/spec/Skill，后者只保存证据支持的跨会话经验。
- R6：Project Lessons 必须通过普通工具显式召回、记住和忘记；动态内容不做隐藏 prompt 注入，写/删复用现有确认与审计边界。
- R7：持久化必须复用 `ProjectIdentity` / `project_storage_dir`，使用一个严格原子 JSON 快照；召回使用有界确定性扫描。
- R8：当前源码、测试和项目指令始终高于记忆；冲突不得按“时间戳新者胜”自动裁决。
- R9：列出被拒绝的方案、取舍、风险、验证路径和可独立回滚的实施切片。
- R10：遵守项目原则：不保留向后兼容、不引入 speculative abstraction、不增加无证据的新依赖、保持 Runtime 与 Plan 解耦。

## Acceptance Criteria

- [x] 外部设计的每个主要组件都被归类为“保留、简化、复用现有能力、延后或删除”，并给出第一性原理依据。
- [x] 当前架构描述有源码、测试、spec 或当前任务证据支撑，且明确当前不存在生产 Memory feature。
- [x] `design.md` 给出一个单一推荐方案，边界和状态所有权无歧义，最小版本可以独立闭环。
- [x] `design.md` 明确哪些内容不属于 Memory：canonical Session、Context Compaction、Supervisor Checkpoint、Trellis/spec/skill 等。
- [x] 推荐方案不包含 Hook/Wrapper、后台 LLM 提炼、SQLite/FTS、向量检索、定时维护、隐藏动态注入、CLI/TUI 或多类型状态机。
- [x] 推荐方案使默认 Full 产品加载已有项目指令，并通过 ToolRuntime 提供有界、可审计、需确认的 Project Lessons 操作。
- [x] `implement.md` 将实施拆成职责单一、可验证、可回滚的步骤，并包含定向测试、架构门禁和全量质量门禁。
- [x] 规划产物通过 Trellis 校验；除任务目录外不改产品文件，不触碰现有未跟踪文件。

## Out of Scope

- 产品代码实现、`task.py start`、推送或创建 PR。
- 云端服务、向量数据库、多 Agent 共享记忆、跨用户记忆。
- 恢复旧版 Memory / Dream / Learning API、迁移层、fallback 或 deprecated alias。
- 为尚未观测到的规模问题实现定时衰减、LLM consolidation、TUI viewer 或复杂评分模型。
- 把旧 Session Memory、MemoryCoordinator、Dream、Learning、ProjectionLayer 或 `_CAP_MEMORY` 以新名字恢复。
