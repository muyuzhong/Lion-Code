# PR2 新增 Session handoff

Parent：`08-22-memory-system-design-convergence`（对应其 implement.md 的 PR2 段）

## Goal

把未完成任务以九段有界摘要带入新 Session，保留旧 Session 完整历史。用户上下文不足切换新会话时，无需手工重写任务目标、已完成工作、当前状态和下一步。

## UX 决策（已确认）

采用**显式 handoff 操作**（`handoff_session` / “携带当前任务新建会话”）。普通 `new_session` / clear 保持干净会话语义，不自动携带未完成任务。

## Requirements

- R1：在 application/facade/SessionPort 层定义显式 handoff 操作；普通 new/clear 语义保持不变。
- R2：复用现有 `ContextCompactor` 与固定 `SUMMARY_HEADINGS`（九段：Objective、Constraints、Decisions、Repository State、Findings、Failed Attempts、Completed Work、Remaining Work、Verification），不得发明第二套 handoff prompt。
- R3：给 `SessionRecorder` 增加窄 `record_branch_summary` 路径，用 `BranchSummaryEntry` 作为新 canonical Session 的首段上下文。
- R4：handoff 必须保留旧 Session 的 append-only 历史；只把有界摘要写入新 Session，不复制旧 raw messages。
- R5：handoff 失败时不得清空旧 Session 或留下半初始化新 Session；确定创建/切换顺序和失败回滚。
- R6：不把任务进度写入长期/项目语义记忆库（Memory 由 PR3/PR4 另行交付，本 PR 不依赖）。
- R7：TUI/server 只增加必要入口和清晰通知，不增加独立 Task store。

## Acceptance Criteria

- [ ] 摘要内容测试：九段完整、source branch root 正确。
- [ ] 旧 Session 历史保留测试：handoff 后旧 messages 不变、仍可 restore。
- [ ] 新上下文有界测试：新 Session 首段为 BranchSummaryEntry 且不超预算。
- [ ] restore/handoff chain 测试：连续 handoff 可追溯。
- [ ] 失败原子性测试：compaction 失败或写入失败时旧 Session 完好、无半初始化新 Session。
- [ ] CI 基线全绿；Session/Compaction ownership 架构测试不回归。

## Out of Scope

- Semantic Memory（PR3/PR4）。
- AGENTS 加载（PR1）。
- 自动 handoff、任务进度入语义记忆。

## 回滚点

删除 handoff 入口与 writer；旧 Session 和已存在 BranchSummaryEntry 仍由现有 canonical replay 支持。
